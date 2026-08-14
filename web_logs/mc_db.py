"""Access layer for the PumpeCraft Minecraft plugin database.

This is a *separate* MariaDB instance from the PumBot panel database, so it gets
its own connection settings (``MC_DB_*`` in the .env) and its own module.
Most operations are read-only. Moderation users can additionally complete
reports and create player notes through narrowly scoped write functions.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

try:
    from .config import Config
    from .datetime_format import BERLIN_TZ, berlin_today, format_berlin_datetime
except ImportError:  # pragma: no cover - direct script execution
    from config import Config
    from datetime_format import BERLIN_TZ, berlin_today, format_berlin_datetime

logger = logging.getLogger("web_logs.mc_db")

# Punishment types that lock a player out of the server.
BAN_TYPES = ("BAN", "TEMPBAN", "IPBAN")


class MinecraftDatabaseUnavailable(RuntimeError):
    """Raised when the Minecraft database is not configured or unreachable."""


def is_configured() -> bool:
    return bool(Config.MC_DB_NAME and Config.MC_DB_USER)


def now_ms() -> int:
    return int(time.time() * 1000)


class MinecraftConnection:
    def __init__(self) -> None:
        if not is_configured():
            raise MinecraftDatabaseUnavailable(
                "Minecraft-Datenbank ist nicht konfiguriert. "
                "Setze MC_DB_HOST, MC_DB_PORT, MC_DB_NAME, MC_DB_USER und "
                "MC_DB_PASSWORD in der .env."
            )
        try:
            self.conn = pymysql.connect(
                host=Config.MC_DB_HOST,
                port=Config.MC_DB_PORT,
                user=Config.MC_DB_USER,
                password=Config.MC_DB_PASSWORD,
                database=Config.MC_DB_NAME,
                charset=Config.MC_DB_CHARSET,
                cursorclass=DictCursor,
                autocommit=True,
                connect_timeout=Config.MC_DB_CONNECT_TIMEOUT,
                read_timeout=Config.MC_DB_READ_TIMEOUT,
                # MariaDB TIMESTAMP values are converted to the session timezone.
                # Fetch them as UTC so the display formatter applies Berlin time once.
                init_command="SET time_zone = '+00:00'",
            )
        except pymysql.MySQLError as exc:
            raise MinecraftDatabaseUnavailable(
                f"Verbindung zur Minecraft-Datenbank fehlgeschlagen: {exc}"
            ) from exc

    def __enter__(self) -> "MinecraftConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.conn.close()

    def query(self, sql: str, params: Any = None) -> list[dict]:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
        except pymysql.MySQLError as exc:
            logger.exception("Minecraft query failed")
            raise MinecraftDatabaseUnavailable(
                f"Abfrage der Minecraft-Datenbank fehlgeschlagen: {exc}"
            ) from exc

    def query_one(self, sql: str, params: Any = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Any = None, default: Any = 0) -> Any:
        row = self.query_one(sql, params)
        if not row:
            return default
        value = next(iter(row.values()), default)
        return default if value is None else value

    def execute(self, sql: str, params: Any = None) -> int:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(sql, params)
                return int(cursor.rowcount)
        except pymysql.MySQLError as exc:
            logger.exception("Minecraft write failed")
            raise MinecraftDatabaseUnavailable(
                f"Änderung in der Minecraft-Datenbank fehlgeschlagen: {exc}"
            ) from exc


def _connect() -> MinecraftConnection:
    return MinecraftConnection()


def check_connection() -> str | None:
    """Return None when the database is reachable, otherwise an error message."""
    try:
        with _connect() as conn:
            conn.scalar("SELECT 1")
        return None
    except MinecraftDatabaseUnavailable as exc:
        return str(exc)
    except pymysql.MySQLError as exc:  # pragma: no cover - network dependent
        return f"Minecraft-Datenbank nicht erreichbar: {exc}"


# ══════════ Formatting helpers ══════════


def format_epoch_millis(value: Any, fallback: str = "—") -> str:
    if value in (None, "", 0):
        return fallback
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return fallback
    moment = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    return format_berlin_datetime(moment, fallback=fallback)


def format_duration(seconds: Any, fallback: str = "0m") -> str:
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return fallback
    if total <= 0:
        return fallback
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def format_bytes(value: Any, fallback: str = "—") -> str:
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        return fallback
    if size <= 0:
        return fallback
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1024.0 or candidate == units[-1]:
            break
        amount /= 1024.0
    precision = 0 if amount >= 100 else 1
    return f"{amount:.{precision}f} {unit}".replace(".", ",")


def format_uptime(seconds: Any, fallback: str = "—") -> str:
    try:
        total = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        return fallback
    if total <= 0:
        return fallback
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def head_url(player_uuid: str | None, size: int = 64) -> str | None:
    """Minecraft head render for a UUID (external avatar service)."""
    if not player_uuid or not Config.MC_HEAD_BASE_URL:
        return None
    return f"{Config.MC_HEAD_BASE_URL.rstrip('/')}/{player_uuid}/{size}"


def is_mute_active(row: dict) -> bool:
    if row.get("unmuted_at"):
        return False
    try:
        return int(row.get("expires_at") or 0) > now_ms()
    except (TypeError, ValueError):
        return False


def is_ban_active(row: dict) -> bool:
    if row.get("revoked_at"):
        return False
    expires_at = row.get("expires_at")
    if expires_at in (None, ""):
        return True  # permanent
    try:
        return int(expires_at) > now_ms()
    except (TypeError, ValueError):
        return False


def mute_status(row: dict) -> str:
    if row.get("unmuted_at"):
        return "Aufgehoben"
    return "Aktiv" if is_mute_active(row) else "Abgelaufen"


def ban_status(row: dict) -> str:
    if row.get("revoked_at"):
        return "Aufgehoben"
    return "Aktiv" if is_ban_active(row) else "Abgelaufen"


# ══════════ Schema-Erkennung ══════════

# Die Lifecycle-Spalten kommen mit Migration V3 des Plugins. Panel und Plugin
# werden getrennt deployt, deshalb wird ihr Vorhandensein einmalig geprüft
# statt vorausgesetzt.
_lifecycle_lock = threading.Lock()
_lifecycle_supported: bool | None = None


def lifecycle_supported() -> bool:
    global _lifecycle_supported
    if _lifecycle_supported is None:
        with _lifecycle_lock:
            if _lifecycle_supported is None:
                with _connect() as conn:
                    rows = conn.query(
                        """SELECT TABLE_NAME
                             FROM INFORMATION_SCHEMA.COLUMNS
                            WHERE TABLE_SCHEMA = DATABASE()
                              AND ((TABLE_NAME = 'pc_punishments' AND COLUMN_NAME = 'revoked_at')
                                OR (TABLE_NAME = 'pc_mutes' AND COLUMN_NAME = 'unmuted_at'))"""
                    )
                _lifecycle_supported = len(rows) == 2
    return _lifecycle_supported


def _not_revoked(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}revoked_at IS NULL" if lifecycle_supported() else ""


def _not_unmuted(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}unmuted_at IS NULL" if lifecycle_supported() else ""


# pc_players kommt mit Migration V4 und wird vom Skills-Plugin bei jedem Login
# gepflegt. Sobald die Tabelle da ist, ersetzt sie die Mojang-Abfrage.
_players_table_lock = threading.Lock()
_players_table_supported: bool | None = None


def players_table_supported() -> bool:
    global _players_table_supported
    if _players_table_supported is None:
        with _players_table_lock:
            if _players_table_supported is None:
                with _connect() as conn:
                    rows = conn.query(
                        """SELECT TABLE_NAME
                             FROM INFORMATION_SCHEMA.TABLES
                            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pc_players'"""
                    )
                _players_table_supported = bool(rows)
    return _players_table_supported


_moderation_schema_lock = threading.Lock()
_moderation_schema_cache: dict[str, bool] = {}


def _table_supported(table_name: str) -> bool:
    with _moderation_schema_lock:
        cached = _moderation_schema_cache.get(table_name)
        if cached is True:
            return True
        with _connect() as conn:
            present = bool(
                conn.scalar(
                    """SELECT COUNT(*) AS total
                         FROM INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
                    (table_name,),
                )
            )
        if present:
            _moderation_schema_cache[table_name] = True
        else:
            _moderation_schema_cache.pop(table_name, None)
        return present


def _column_supported(table_name: str, column_name: str) -> bool:
    cache_key = f"{table_name}.{column_name}"
    with _moderation_schema_lock:
        cached = _moderation_schema_cache.get(cache_key)
        if cached is True:
            return True
        with _connect() as conn:
            present = bool(
                conn.scalar(
                    """SELECT COUNT(*) AS total
                         FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
                    (table_name, column_name),
                )
            )
        if present:
            _moderation_schema_cache[cache_key] = True
        else:
            _moderation_schema_cache.pop(cache_key, None)
        return present


def moderation_notes_supported() -> bool:
    return _table_supported("pc_player_notes") and _table_supported(
        "pc_anticheat_events"
    )


def report_closure_supported() -> bool:
    return _column_supported("pc_reports", "closed_at")


# ══════════ Name resolution ══════════

# The plugin only stores player names on moderation rows (reports, mutes,
# punishments, warnings). Playtime and death counters are keyed by UUID only, so
# names are resolved from those tables first and — optionally — via the Mojang
# profile API for players that were never moderated.

_NAME_UNION = """
    SELECT reporter_uuid AS player_uuid, reporter_name AS player_name, created_at AS seen_at
      FROM pc_reports
    UNION ALL
    SELECT target_uuid, target_name, created_at FROM pc_reports
    UNION ALL
    SELECT target_uuid, target_name, muted_at FROM pc_mutes
    UNION ALL
    SELECT target_uuid, target_name, created_at FROM pc_punishments
    UNION ALL
    SELECT target_uuid, target_name, created_at FROM pc_warnings
"""

_MOJANG_PROFILE_URL = "https://sessionserver.mojang.com/session/minecraft/profile/{uuid}"
_MOJANG_TTL_SECONDS = 12 * 3600
_MOJANG_MISS_TTL_SECONDS = 15 * 60
_mojang_cache: dict[str, tuple[float, str | None]] = {}
_mojang_lock = threading.Lock()


def _mojang_cached(player_uuid: str) -> tuple[bool, str | None]:
    with _mojang_lock:
        entry = _mojang_cache.get(player_uuid)
    if not entry:
        return False, None
    expires_at, name = entry
    if expires_at <= time.time():
        with _mojang_lock:
            _mojang_cache.pop(player_uuid, None)
        return False, None
    return True, name


def _mojang_store(player_uuid: str, name: str | None) -> None:
    ttl = _MOJANG_TTL_SECONDS if name else _MOJANG_MISS_TTL_SECONDS
    with _mojang_lock:
        _mojang_cache[player_uuid] = (time.time() + ttl, name)


def _mojang_fetch(player_uuid: str) -> str | None:
    import requests  # local import: only needed when lookups are enabled

    try:
        response = requests.get(
            _MOJANG_PROFILE_URL.format(uuid=player_uuid.replace("-", "")),
            timeout=Config.MC_NAME_LOOKUP_TIMEOUT,
        )
    except Exception as exc:  # network hiccup, DNS, timeout, ...
        logger.debug("Mojang lookup failed for %s: %s", player_uuid, exc)
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json().get("name")
    except ValueError:
        return None


def _mojang_names(uuids: list[str]) -> dict[str, str]:
    """Resolve UUIDs via the Mojang API, cached in memory."""
    if not Config.MC_NAME_LOOKUP or not uuids:
        return {}

    resolved: dict[str, str] = {}
    pending: list[str] = []
    for player_uuid in uuids:
        hit, name = _mojang_cached(player_uuid)
        if hit:
            if name:
                resolved[player_uuid] = name
        else:
            pending.append(player_uuid)

    pending = pending[: Config.MC_NAME_LOOKUP_MAX]
    if not pending:
        return resolved

    with ThreadPoolExecutor(max_workers=min(8, len(pending))) as pool:
        for player_uuid, name in zip(pending, pool.map(_mojang_fetch, pending)):
            _mojang_store(player_uuid, name)
            if name:
                resolved[player_uuid] = name
    return resolved


def known_names(conn: MinecraftConnection) -> dict[str, str]:
    """
    Bekannter Name je UUID. Basis sind die Moderations-Tabellen; die von den
    Plugins gepflegte pc_players hat Vorrang, weil sie bei jedem Login
    aktualisiert wird.
    """
    rows = conn.query(
        f"""SELECT player_uuid, player_name, MAX(seen_at) AS seen_at
              FROM ({_NAME_UNION}) AS known
             WHERE player_name IS NOT NULL AND player_name <> ''
             GROUP BY player_uuid, player_name"""
    )
    latest: dict[str, tuple[int, str]] = {}
    for row in rows:
        player_uuid = row["player_uuid"]
        seen_at = int(row.get("seen_at") or 0)
        current = latest.get(player_uuid)
        if current is None or seen_at >= current[0]:
            latest[player_uuid] = (seen_at, row["player_name"])

    names = {uuid: name for uuid, (_, name) in latest.items()}

    if players_table_supported():
        for row in conn.query(
            "SELECT player_uuid, player_name FROM pc_players WHERE player_name <> ''"
        ):
            names[row["player_uuid"]] = row["player_name"]

    return names


def resolve_names(
    conn: MinecraftConnection, uuids: list[str], *, allow_lookup: bool = True
) -> dict[str, str]:
    wanted = [player_uuid for player_uuid in dict.fromkeys(uuids) if player_uuid]
    if not wanted:
        return {}
    names = {
        player_uuid: name
        for player_uuid, name in known_names(conn).items()
        if player_uuid in set(wanted)
    }
    if allow_lookup:
        missing = [player_uuid for player_uuid in wanted if player_uuid not in names]
        names.update(_mojang_names(missing))
    return names


def decorate_player(
    row: dict,
    uuid_field: str,
    names: dict[str, str],
    prefix: str = "player",
) -> dict:
    """Attach display name / head avatar for a UUID column."""
    item = dict(row)
    player_uuid = item.get(uuid_field)
    item[f"{prefix}_uuid"] = player_uuid
    item[f"{prefix}_name"] = (
        item.get(f"{prefix}_name")
        or names.get(player_uuid)
        or (player_uuid or "—")
    )
    item[f"{prefix}_head_url"] = head_url(player_uuid)
    return item


# ══════════ Overview ══════════


def get_overview() -> dict:
    right_now = now_ms()
    with _connect() as conn:
        players = conn.scalar(
            f"""SELECT COUNT(*) AS total FROM (
                    SELECT player_uuid FROM pc_playtime
                    UNION SELECT player_uuid FROM pc_death_counts
                    UNION SELECT reporter_uuid FROM pc_reports
                    UNION SELECT target_uuid FROM pc_reports
                    UNION SELECT target_uuid FROM pc_mutes
                    UNION SELECT target_uuid FROM pc_punishments
                    UNION SELECT target_uuid FROM pc_warnings
                ) AS everyone"""
        )
        playtime = conn.query_one(
            """SELECT COALESCE(SUM(total_seconds), 0) AS total_seconds,
                      COALESCE(SUM(active_seconds), 0) AS active_seconds,
                      COALESCE(SUM(afk_seconds), 0) AS afk_seconds,
                      COUNT(*) AS tracked_players,
                      MAX(updated_at) AS last_update
                 FROM pc_playtime"""
        ) or {}
        deaths = conn.query_one(
            """SELECT COALESCE(SUM(death_count), 0) AS total_deaths,
                      COUNT(*) AS tracked_players
                 FROM pc_death_counts"""
        ) or {}
        reports_open = conn.scalar(
            "SELECT COUNT(*) AS total FROM pc_reports WHERE is_open = 1"
        )
        reports_total = conn.scalar("SELECT COUNT(*) AS total FROM pc_reports")
        mutes_active = conn.scalar(
            f"SELECT COUNT(*) AS total FROM pc_mutes WHERE expires_at > %s{_not_unmuted()}",
            (right_now,),
        )
        mutes_total = conn.scalar("SELECT COUNT(*) AS total FROM pc_mutes")
        bans_active = conn.scalar(
            f"""SELECT COUNT(*) AS total
                  FROM pc_punishments
                 WHERE punishment_type IN ({", ".join(["%s"] * len(BAN_TYPES))})
                   AND (expires_at IS NULL OR expires_at > %s){_not_revoked()}""",
            (*BAN_TYPES, right_now),
        )
        bans_total = conn.scalar("SELECT COUNT(*) AS total FROM pc_punishments")
        warnings_total = conn.scalar("SELECT COUNT(*) AS total FROM pc_warnings")
        schema = conn.query_one(
            """SELECT version, description, installed_on
                 FROM flyway_schema_history
                WHERE success = 1
                ORDER BY installed_rank DESC
                LIMIT 1"""
        )

    total_seconds = int(playtime.get("total_seconds") or 0)
    afk_seconds = int(playtime.get("afk_seconds") or 0)
    return {
        "players": int(players or 0),
        "total_seconds": total_seconds,
        "active_seconds": int(playtime.get("active_seconds") or 0),
        "afk_seconds": afk_seconds,
        # Online-Zeit ohne AFK. "active_seconds" zählt nur Sekunden mit echter
        # Aktion (Bewegung/Interaktion) und ist deshalb immer kleiner.
        "nonafk_seconds": max(0, total_seconds - afk_seconds),
        "playtime_players": int(playtime.get("tracked_players") or 0),
        "playtime_last_update": playtime.get("last_update"),
        "total_deaths": int(deaths.get("total_deaths") or 0),
        "death_players": int(deaths.get("tracked_players") or 0),
        "reports_open": int(reports_open or 0),
        "reports_total": int(reports_total or 0),
        "mutes_active": int(mutes_active or 0),
        "mutes_total": int(mutes_total or 0),
        "bans_active": int(bans_active or 0),
        "bans_total": int(bans_total or 0),
        "warnings_total": int(warnings_total or 0),
        "schema_version": (schema or {}).get("version"),
        "schema_description": (schema or {}).get("description"),
        "schema_installed_on": (schema or {}).get("installed_on"),
    }


# ══════════ Players ══════════

CHART_DAYS = (7, 30, 90, 365)
ALL_TIME_CHART_DAYS = 0
SERVER_CHART_HOURS = (1, 6, 24, 168)
ALL_TIME_CHART_HOURS = 0
MODERATION_CHART_METRICS = {"reports", "bans", "warnings", "mutes"}
EVENT_CHART_DEFINITIONS = {
    "chat": ("pc_chat_messages", "created_at", "Chatnachrichten", "#22d3ee"),
    "reports": ("pc_reports", "created_at", "Reports", "#fb7185"),
    "bans": ("pc_punishments", "created_at", "Bans", "#f87171"),
    "warnings": ("pc_warnings", "created_at", "Verwarnungen", "#fbbf24"),
    "mutes": ("pc_mutes", "muted_at", "Mutes", "#c084fc"),
}


def _chart_dates(days: int, earliest: date | None = None) -> list[date]:
    today = berlin_today()
    if days == ALL_TIME_CHART_DAYS:
        start = min(earliest or today, today)
        safe_days = (today - start).days + 1
    else:
        safe_days = days if days in CHART_DAYS else 30
    return [today - timedelta(days=offset) for offset in range(safe_days - 1, -1, -1)]


def _date_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _epoch_millis_date(value: Any) -> date | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).astimezone(
        BERLIN_TZ
    ).date()


def _first_chart_date(metric: str, player_uuid: str | None = None) -> date | None:
    params: tuple[Any, ...] = ()
    if metric == "players":
        sql = "SELECT MIN(first_seen) AS first_value FROM pc_players WHERE first_seen > 0"
        epoch_millis = True
    elif metric == "playtime":
        if not _table_supported("pc_playtime_history"):
            return None
        player_filter = " WHERE player_uuid = %s" if player_uuid else ""
        params = (player_uuid,) if player_uuid else ()
        sql = f"SELECT MIN(snapshot_date) AS first_value FROM pc_playtime_history{player_filter}"
        epoch_millis = False
    else:
        definition = EVENT_CHART_DEFINITIONS.get(metric)
        if definition is None or not _table_supported(definition[0]):
            return None
        table, time_column, _, _ = definition
        sql = f"SELECT MIN({time_column}) AS first_value FROM {table}"
        epoch_millis = True

    with _connect() as conn:
        row = conn.query_one(sql, params) or {}
    value = row.get("first_value")
    if epoch_millis:
        return _epoch_millis_date(value)
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def get_player_growth_summary(days: int = 30) -> dict:
    dates = _chart_dates(days)
    start_ms = int(datetime.combine(dates[0], datetime.min.time()).timestamp() * 1000)
    has_platform = _column_supported("pc_players", "platform")
    platform_sql = "platform" if has_platform else "'UNKNOWN'"
    with _connect() as conn:
        row = conn.query_one(
            f"""SELECT COUNT(*) AS total,
                       SUM({platform_sql} = 'JAVA') AS java_count,
                       SUM({platform_sql} = 'BEDROCK') AS bedrock_count,
                       SUM({platform_sql} NOT IN ('JAVA', 'BEDROCK')) AS unknown_count,
                       SUM(first_seen >= %s) AS growth
                  FROM pc_players""",
            (start_ms,),
        ) or {}
    return {
        "total": int(row.get("total") or 0),
        "java": int(row.get("java_count") or 0),
        "bedrock": int(row.get("bedrock_count") or 0),
        "unknown": int(row.get("unknown_count") or 0),
        "growth": int(row.get("growth") or 0),
        "days": len(dates),
    }


def _event_chart(metric: str, dates: list[date]) -> dict:
    table, time_column, label, color = EVENT_CHART_DEFINITIONS[metric]
    values = {day.isoformat(): 0 for day in dates}
    if not _table_supported(table):
        return {"label": label, "color": color, "values": list(values.values())}
    start_ms = int(datetime.combine(dates[0], datetime.min.time()).timestamp() * 1000)
    end_ms = int(
        datetime.combine(dates[-1] + timedelta(days=1), datetime.min.time()).timestamp()
        * 1000
    )
    with _connect() as conn:
        rows = conn.query(
            f"""SELECT DATE(FROM_UNIXTIME({time_column} / 1000)) AS event_date,
                       COUNT(*) AS event_count
                  FROM {table}
                 WHERE {time_column} >= %s AND {time_column} < %s
                 GROUP BY event_date""",
            (start_ms, end_ms),
        )
    for row in rows:
        key = _date_key(row.get("event_date"))
        if key in values:
            values[key] = int(row.get("event_count") or 0)
    return {"label": label, "color": color, "values": list(values.values())}


def _player_growth_chart(dates: list[date]) -> list[dict]:
    has_platform = _column_supported("pc_players", "platform")
    platform_sql = "platform" if has_platform else "'UNKNOWN'"
    end_ms = int(
        datetime.combine(dates[-1] + timedelta(days=1), datetime.min.time()).timestamp()
        * 1000
    )
    with _connect() as conn:
        rows = conn.query(
            f"""SELECT DATE(FROM_UNIXTIME(first_seen / 1000)) AS first_seen_date,
                       {platform_sql} AS platform,
                       COUNT(*) AS player_count
                  FROM pc_players
                 WHERE first_seen > 0 AND first_seen < %s
                 GROUP BY first_seen_date, {platform_sql}
                 ORDER BY first_seen_date""",
            (end_ms,),
        )

    start_key = dates[0].isoformat()
    additions: dict[str, dict[str, int]] = {}
    totals = {"JAVA": 0, "BEDROCK": 0, "UNKNOWN": 0}
    for row in rows:
        key = _date_key(row.get("first_seen_date"))
        platform = str(row.get("platform") or "UNKNOWN").upper()
        if platform not in totals:
            platform = "UNKNOWN"
        count = int(row.get("player_count") or 0)
        if key < start_key:
            totals[platform] += count
        else:
            additions.setdefault(key, {}).setdefault(platform, 0)
            additions[key][platform] += count

    output = {platform: [] for platform in totals}
    output["TOTAL"] = []
    for day in dates:
        for platform, count in additions.get(day.isoformat(), {}).items():
            totals[platform] += count
        for platform in totals:
            output[platform].append(totals[platform])
        output["TOTAL"].append(sum(totals.values()))

    series = [
        {"label": "Gesamt", "color": "#22d3ee", "values": output["TOTAL"]},
        {"label": "Java", "color": "#34d399", "values": output["JAVA"]},
        {"label": "Bedrock", "color": "#fbbf24", "values": output["BEDROCK"]},
    ]
    if any(output["UNKNOWN"]):
        series.append(
            {"label": "Unbekannt", "color": "#94a3b8", "values": output["UNKNOWN"]}
        )
    return series


def _playtime_chart(dates: list[date], player_uuid: str | None = None) -> list[dict]:
    if not _table_supported("pc_playtime_history"):
        return []
    params: list[Any] = [dates[-1]]
    player_filter = ""
    if player_uuid:
        player_filter = " AND player_uuid = %s"
        params.append(player_uuid)
    with _connect() as conn:
        rows = conn.query(
            f"""SELECT player_uuid, snapshot_date, total_seconds,
                       active_seconds, afk_seconds
                  FROM pc_playtime_history
                 WHERE snapshot_date <= %s{player_filter}
                 ORDER BY snapshot_date, player_uuid""",
            tuple(params),
        )

    by_day: dict[str, list[dict]] = {}
    latest: dict[str, dict] = {}
    start_key = dates[0].isoformat()
    for row in rows:
        key = _date_key(row.get("snapshot_date"))
        if key < start_key:
            latest[str(row["player_uuid"])] = row
        else:
            by_day.setdefault(key, []).append(row)

    totals: list[int | None] = []
    active: list[int | None] = []
    afk: list[int | None] = []
    for day in dates:
        for row in by_day.get(day.isoformat(), []):
            latest[str(row["player_uuid"])] = row
        if not latest:
            totals.append(None)
            active.append(None)
            afk.append(None)
            continue
        totals.append(sum(int(row.get("total_seconds") or 0) for row in latest.values()))
        active.append(sum(int(row.get("active_seconds") or 0) for row in latest.values()))
        afk.append(sum(int(row.get("afk_seconds") or 0) for row in latest.values()))

    return [
        {"label": "Gesamt", "color": "#22d3ee", "values": totals},
        {"label": "Aktiv", "color": "#34d399", "values": active},
        {"label": "AFK", "color": "#fbbf24", "values": afk},
    ]


def get_statistics_chart(metric: str = "players", days: int = 30) -> dict:
    safe_days = (
        days
        if days in CHART_DAYS or days == ALL_TIME_CHART_DAYS
        else 30
    )
    valid_metrics = {"players", "playtime", "chat"} | MODERATION_CHART_METRICS
    safe_metric = metric if metric in valid_metrics else "players"
    first_date = _first_chart_date(safe_metric)
    dates = _chart_dates(
        safe_days,
        earliest=first_date if safe_days == ALL_TIME_CHART_DAYS else None,
    )
    metadata = {
        "players": ("Spielerzuwachs", "Registrierte Spieler", "count"),
        "playtime": ("Playtime", "Kumulierte Server-Spielzeit", "seconds"),
        "chat": ("Chataktivität", "Nachrichten pro Tag", "count"),
        "reports": ("Reports", "Neue Reports pro Tag", "count"),
        "bans": ("Bans", "Ausgesprochene Bans pro Tag", "count"),
        "warnings": ("Verwarnungen", "Verwarnungen pro Tag", "count"),
        "mutes": ("Mutes", "Ausgesprochene Mutes pro Tag", "count"),
    }
    title, subtitle, unit = metadata[safe_metric]
    if safe_metric == "playtime" and first_date is not None:
        subtitle += f" · Verlauf seit {first_date:%d.%m.%Y}"
    if safe_metric == "players":
        series = _player_growth_chart(dates)
    elif safe_metric == "playtime":
        series = _playtime_chart(dates)
    else:
        series = [_event_chart(safe_metric, dates)]
    return {
        "metric": safe_metric,
        "days": safe_days,
        "all_time": safe_days == ALL_TIME_CHART_DAYS,
        "history_start": first_date.isoformat() if first_date else None,
        "title": title,
        "subtitle": subtitle,
        "unit": unit,
        "labels": [day.isoformat() for day in dates],
        "series": series,
    }


def get_player_playtime_chart(player_uuid: str, days: int = 30) -> dict:
    safe_days = (
        days
        if days in CHART_DAYS or days == ALL_TIME_CHART_DAYS
        else 30
    )
    first_date = _first_chart_date("playtime", player_uuid)
    dates = _chart_dates(
        safe_days,
        earliest=first_date if safe_days == ALL_TIME_CHART_DAYS else None,
    )
    subtitle = "Gesamt, Aktiv und AFK pro Tag"
    if first_date is not None:
        subtitle += f" · Verlauf seit {first_date:%d.%m.%Y}"
    return {
        "metric": "playtime",
        "days": safe_days,
        "all_time": safe_days == ALL_TIME_CHART_DAYS,
        "history_start": first_date.isoformat() if first_date else None,
        "title": "Playtime-Verlauf",
        "subtitle": subtitle,
        "unit": "seconds",
        "labels": [day.isoformat() for day in dates],
        "series": _playtime_chart(dates, player_uuid),
    }


def get_playtime_live(player_uuid: str | None = None) -> dict:
    with _connect() as conn:
        server = conn.query_one(
            """SELECT COALESCE(SUM(total_seconds), 0) AS total_seconds,
                      COALESCE(SUM(active_seconds), 0) AS active_seconds,
                      COALESCE(SUM(afk_seconds), 0) AS afk_seconds,
                      MAX(updated_at) AS updated_at
                 FROM pc_playtime"""
        ) or {}
        player = None
        if player_uuid:
            player = conn.query_one(
                """SELECT total_seconds, active_seconds, afk_seconds, updated_at
                     FROM pc_playtime
                    WHERE player_uuid = %s""",
                (player_uuid,),
            )
    return {"server": server, "player": player}


def server_metrics_supported() -> bool:
    return _table_supported("pc_server_specs") and _table_supported(
        "pc_server_metrics"
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_server_performance() -> dict:
    if not server_metrics_supported():
        return {"supported": False, "latest": None, "specs": None, "summary": {}}
    since = now_ms() - 24 * 60 * 60 * 1000
    with _connect() as conn:
        latest = conn.query_one(
            "SELECT * FROM pc_server_metrics ORDER BY captured_at DESC LIMIT 1"
        )
        specs = conn.query_one("SELECT * FROM pc_server_specs WHERE server_id = 1")
        summary = conn.query_one(
            """SELECT COUNT(*) AS samples,
                      AVG(tps_1m) AS average_tps,
                      MIN(tps_1m) AS minimum_tps,
                      AVG(mspt) AS average_mspt,
                      MAX(mspt) AS maximum_mspt,
                      SUM(tps_1m < 18 OR mspt > 50) AS lag_samples
                 FROM pc_server_metrics
                WHERE captured_at >= %s""",
            (since,),
        ) or {}

    if latest:
        for key in (
            "tps_1m", "tps_5m", "tps_15m", "mspt",
            "process_cpu_percent", "system_cpu_percent",
        ):
            latest[key] = _float_or_none(latest.get(key))
        memory_max = int(latest.get("memory_max_bytes") or 0)
        disk_total = int(latest.get("disk_total_bytes") or 0)
        latest["memory_percent"] = round(
            int(latest.get("memory_used_bytes") or 0) / memory_max * 100, 1
        ) if memory_max else 0.0
        latest["disk_percent"] = round(
            int(latest.get("disk_used_bytes") or 0) / disk_total * 100, 1
        ) if disk_total else 0.0
        tps = float(latest.get("tps_1m") or 0)
        mspt = float(latest.get("mspt") or 0)
        if tps < 15 or mspt >= 70:
            latest["status"] = "critical"
            latest["status_label"] = "Kritisch"
        elif tps < 18 or mspt >= 50:
            latest["status"] = "warning"
            latest["status_label"] = "Belastet"
        else:
            latest["status"] = "healthy"
            latest["status_label"] = "Stabil"

    for key in ("average_tps", "minimum_tps", "average_mspt", "maximum_mspt"):
        summary[key] = _float_or_none(summary.get(key))
    summary["samples"] = int(summary.get("samples") or 0)
    summary["lag_samples"] = int(summary.get("lag_samples") or 0)
    return {"supported": True, "latest": latest, "specs": specs, "summary": summary}


def get_server_performance_chart(metric: str = "tps", hours: int = 6) -> dict:
    safe_hours = (
        hours
        if hours in SERVER_CHART_HOURS or hours == ALL_TIME_CHART_HOURS
        else 6
    )
    valid_metrics = {"tps", "mspt", "cpu", "memory", "players", "chunks", "entities"}
    safe_metric = metric if metric in valid_metrics else "tps"
    metadata = {
        "tps": ("TPS-Verlauf", "Ticks pro Sekunde", "decimal"),
        "mspt": ("MSPT-Verlauf", "Millisekunden pro Tick", "ms"),
        "cpu": ("CPU-Auslastung", "Java-Prozess und Gesamtsystem", "percent"),
        "memory": ("RAM-Auslastung", "Belegter Java-Heap", "percent"),
        "players": ("Online-Spieler", "Spieler pro Messpunkt", "count"),
        "chunks": ("Geladene Chunks", "Chunks über alle Welten", "count"),
        "entities": ("Geladene Entities", "Entities über alle Welten", "count"),
    }
    title, subtitle, unit = metadata[safe_metric]
    if not server_metrics_supported():
        return {
            "metric": safe_metric, "hours": safe_hours, "title": title,
            "subtitle": subtitle, "unit": unit, "label_format": "datetime",
            "all_time": safe_hours == ALL_TIME_CHART_HOURS,
            "labels": [], "series": [],
        }

    current_ms = now_ms()
    if safe_hours == ALL_TIME_CHART_HOURS:
        with _connect() as conn:
            first_captured = int(
                conn.scalar(
                    "SELECT MIN(captured_at) AS first_captured FROM pc_server_metrics",
                    default=current_ms,
                )
                or current_ms
            )
        since = min(first_captured, current_ms)
        span_hours = max(1, (current_ms - since + 3_599_999) // 3_600_000)
    else:
        span_hours = safe_hours
        since = current_ms - safe_hours * 60 * 60 * 1000
    if span_hours <= 1:
        bucket_minutes = 1
    elif span_hours <= 6:
        bucket_minutes = 2
    elif span_hours <= 24:
        bucket_minutes = 5
    elif span_hours <= 168:
        bucket_minutes = 30
    elif span_hours <= 720:
        bucket_minutes = 120
    else:
        bucket_minutes = 1440
    bucket_ms = bucket_minutes * 60 * 1000
    expressions = {
        "tps": (
            ("1 Minute", "AVG(tps_1m)", "#22d3ee"),
            ("5 Minuten", "AVG(tps_5m)", "#34d399"),
            ("15 Minuten", "AVG(tps_15m)", "#fbbf24"),
        ),
        "mspt": (("MSPT", "AVG(mspt)", "#fbbf24"),),
        "cpu": (
            ("Java-Prozess", "AVG(process_cpu_percent)", "#22d3ee"),
            ("System", "AVG(system_cpu_percent)", "#fb7185"),
        ),
        "memory": (("RAM", "AVG(memory_used_bytes / NULLIF(memory_max_bytes, 0) * 100)", "#c084fc"),),
        "players": (("Spieler", "AVG(online_players)", "#34d399"),),
        "chunks": (("Chunks", "AVG(loaded_chunks)", "#60a5fa"),),
        "entities": (("Entities", "AVG(entity_count)", "#fb7185"),),
    }[safe_metric]
    select_values = ",\n".join(
        f"{expression} AS value_{index}" for index, (_, expression, _) in enumerate(expressions)
    )
    with _connect() as conn:
        rows = conn.query(
            f"""SELECT FLOOR(captured_at / %s) * %s AS bucket_at,
                       {select_values}
                  FROM pc_server_metrics
                 WHERE captured_at >= %s
                 GROUP BY bucket_at
                 ORDER BY bucket_at""",
            (bucket_ms, bucket_ms, since),
        )

    labels = [
        datetime.fromtimestamp(int(row["bucket_at"]) / 1000, tz=timezone.utc).isoformat()
        for row in rows
    ]
    series = []
    for index, (label, _, color) in enumerate(expressions):
        series.append(
            {
                "label": label,
                "color": color,
                "values": [_float_or_none(row.get(f"value_{index}")) for row in rows],
            }
        )
    return {
        "metric": safe_metric,
        "hours": safe_hours,
        "all_time": safe_hours == ALL_TIME_CHART_HOURS,
        "title": title,
        "subtitle": subtitle,
        "unit": unit,
        "label_format": "datetime",
        "labels": labels,
        "series": series,
    }


_PLAYER_UNIVERSE = """
    SELECT player_uuid, NULL AS player_name FROM pc_playtime
    UNION ALL SELECT player_uuid, NULL FROM pc_death_counts
    UNION ALL SELECT reporter_uuid, reporter_name FROM pc_reports
    UNION ALL SELECT target_uuid, target_name FROM pc_reports
    UNION ALL SELECT target_uuid, target_name FROM pc_mutes
    UNION ALL SELECT target_uuid, target_name FROM pc_punishments
    UNION ALL SELECT target_uuid, target_name FROM pc_warnings
"""

PLAYER_SORTS = {
    "playtime": "total_seconds DESC, death_count DESC",
    "nonafk": (
        "(COALESCE(pt.total_seconds, 0) - COALESCE(pt.afk_seconds, 0)) DESC,"
        " total_seconds DESC"
    ),
    "active": "active_seconds DESC, total_seconds DESC",
    "afk": "afk_seconds DESC, total_seconds DESC",
    "deaths": "death_count DESC, total_seconds DESC",
    "punishments": "punishment_count DESC, warning_count DESC",
    "name": "any_name IS NULL ASC, any_name ASC",
    "recent": "playtime_updated_at IS NULL ASC, playtime_updated_at DESC",
}
DEFAULT_PLAYER_SORT = "playtime"


def _player_scope(q: str = "") -> tuple[str, list[Any]]:
    """Derived table of every known player UUID, optionally filtered by name/UUID."""
    params: list[Any] = []
    having = ""
    if q:
        like = f"%{q}%"
        having = (
            " HAVING u.player_uuid LIKE %s"
            " OR MAX(CASE WHEN u.player_name LIKE %s THEN 1 ELSE 0 END) = 1"
        )
        params.extend([like, like])
    sql = f"""(SELECT u.player_uuid, MAX(u.player_name) AS any_name
                 FROM ({_PLAYER_UNIVERSE}) AS u
                WHERE u.player_uuid IS NOT NULL AND u.player_uuid <> ''
                GROUP BY u.player_uuid{having}) AS p"""
    return sql, params


def count_players(q: str = "") -> int:
    scope_sql, scope_params = _player_scope(q)
    with _connect() as conn:
        return int(
            conn.scalar(
                f"SELECT COUNT(*) AS total FROM {scope_sql}", tuple(scope_params)
            )
            or 0
        )


def list_players(
    q: str = "",
    sort: str = DEFAULT_PLAYER_SORT,
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    scope_sql, scope_params = _player_scope(q)
    order_by = PLAYER_SORTS.get(sort, PLAYER_SORTS[DEFAULT_PLAYER_SORT])
    right_now = now_ms()
    ban_placeholders = ", ".join(["%s"] * len(BAN_TYPES))
    sql = f"""
        SELECT p.player_uuid,
               p.any_name,
               COALESCE(pt.total_seconds, 0) AS total_seconds,
               COALESCE(pt.active_seconds, 0) AS active_seconds,
               COALESCE(pt.afk_seconds, 0) AS afk_seconds,
               pt.updated_at AS playtime_updated_at,
               COALESCE(dc.death_count, 0) AS death_count,
               COALESCE(w.total, 0) AS warning_count,
               COALESCE(pu.total, 0) AS punishment_count,
               COALESCE(rp.total, 0) AS report_count,
               COALESCE(ab.total, 0) AS active_ban_count,
               CASE WHEN mu.expires_at > %s{_not_unmuted("mu")} THEN 1 ELSE 0 END AS muted
          FROM {scope_sql}
          LEFT JOIN pc_playtime pt ON pt.player_uuid = p.player_uuid
          LEFT JOIN pc_death_counts dc ON dc.player_uuid = p.player_uuid
          LEFT JOIN pc_mutes mu ON mu.target_uuid = p.player_uuid
          LEFT JOIN (SELECT target_uuid, COUNT(*) AS total FROM pc_warnings GROUP BY target_uuid) w
                 ON w.target_uuid = p.player_uuid
          LEFT JOIN (SELECT target_uuid, COUNT(*) AS total FROM pc_punishments GROUP BY target_uuid) pu
                 ON pu.target_uuid = p.player_uuid
          LEFT JOIN (SELECT target_uuid, COUNT(*) AS total FROM pc_reports GROUP BY target_uuid) rp
                 ON rp.target_uuid = p.player_uuid
          LEFT JOIN (SELECT target_uuid, COUNT(*) AS total
                       FROM pc_punishments
                      WHERE punishment_type IN ({ban_placeholders})
                        AND (expires_at IS NULL OR expires_at > %s){_not_revoked()}
                      GROUP BY target_uuid) ab
                 ON ab.target_uuid = p.player_uuid
         ORDER BY {order_by}
         LIMIT %s OFFSET %s
    """
    params = [right_now, *scope_params, *BAN_TYPES, right_now, limit, offset]
    with _connect() as conn:
        rows = conn.query(sql, tuple(params))
        names = resolve_names(conn, [row["player_uuid"] for row in rows])
    result = []
    for row in rows:
        item = dict(row)
        item["player_name"] = item.get("any_name") or names.get(item["player_uuid"])
        result.append(decorate_player(item, "player_uuid", names))
    return result


def get_player(player_uuid: str) -> dict | None:
    """Full profile for a single player, including their moderation history."""
    right_now = now_ms()
    has_moderation_notes = moderation_notes_supported()
    with _connect() as conn:
        exists = conn.scalar(
            f"""SELECT COUNT(*) AS total
                  FROM ({_PLAYER_UNIVERSE}) AS u
                 WHERE u.player_uuid = %s""",
            (player_uuid,),
        )
        if not exists:
            return None

        playtime = conn.query_one(
            "SELECT * FROM pc_playtime WHERE player_uuid = %s", (player_uuid,)
        )
        deaths = conn.query_one(
            "SELECT * FROM pc_death_counts WHERE player_uuid = %s", (player_uuid,)
        )
        mute = conn.query_one(
            "SELECT * FROM pc_mutes WHERE target_uuid = %s", (player_uuid,)
        )
        punishments = conn.query(
            """SELECT * FROM pc_punishments
                WHERE target_uuid = %s
                ORDER BY created_at DESC""",
            (player_uuid,),
        )
        warnings = conn.query(
            """SELECT * FROM pc_warnings
                WHERE target_uuid = %s
                ORDER BY created_at DESC""",
            (player_uuid,),
        )
        reports_against = conn.query(
            """SELECT * FROM pc_reports
                WHERE target_uuid = %s
                ORDER BY created_at DESC""",
            (player_uuid,),
        )
        reports_by = conn.query(
            """SELECT * FROM pc_reports
                WHERE reporter_uuid = %s
                ORDER BY created_at DESC""",
            (player_uuid,),
        )
        notes = (
            conn.query(
                """SELECT * FROM pc_player_notes
                    WHERE player_uuid = %s
                    ORDER BY created_at DESC, id DESC""",
                (player_uuid,),
            )
            if has_moderation_notes
            else []
        )
        anticheat_events = (
            conn.query(
                """SELECT * FROM pc_anticheat_events
                    WHERE player_uuid = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 100""",
                (player_uuid,),
            )
            if has_moderation_notes
            else []
        )
        rank = conn.scalar(
            """SELECT COUNT(*) + 1 AS rank_position
                 FROM pc_playtime
                WHERE total_seconds > COALESCE(
                    (SELECT total_seconds FROM pc_playtime WHERE player_uuid = %s), -1
                )""",
            (player_uuid,),
            default=None,
        )
        names = resolve_names(conn, [player_uuid])

    active_bans = [row for row in punishments if is_ban_active(row)]
    return {
        "player_uuid": player_uuid,
        "player_name": names.get(player_uuid) or player_uuid,
        "player_head_url": head_url(player_uuid, 128),
        "has_profile_name": player_uuid in names,
        "playtime": playtime,
        "deaths": deaths,
        "mute": mute if mute and is_mute_active(mute) else None,
        "expired_mute": mute if mute and not is_mute_active(mute) else None,
        "punishments": punishments,
        "active_bans": active_bans,
        "warnings": warnings,
        "reports_against": reports_against,
        "reports_by": reports_by,
        "notes": notes,
        "anticheat_events": anticheat_events,
        "playtime_rank": int(rank) if rank and playtime else None,
        "generated_at": right_now,
    }


# ══════════ Reports ══════════


def _reports_where(q: str = "", status: str = "all") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status == "open":
        clauses.append("is_open = 1")
    elif status == "closed":
        clauses.append("is_open = 0")
    if q:
        like = f"%{q}%"
        clauses.append(
            "(reporter_name LIKE %s OR target_name LIKE %s OR reason LIKE %s"
            " OR reporter_uuid LIKE %s OR target_uuid LIKE %s)"
        )
        params.extend([like] * 5)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_reports(
    q: str = "", status: str = "all", limit: int = 25, offset: int = 0
) -> list[dict]:
    where, params = _reports_where(q, status)
    with _connect() as conn:
        rows = conn.query(
            f"SELECT * FROM pc_reports{where} ORDER BY is_open DESC, created_at DESC"
            " LIMIT %s OFFSET %s",
            tuple([*params, limit, offset]),
        )
    return rows


def count_reports(q: str = "", status: str = "all") -> int:
    where, params = _reports_where(q, status)
    with _connect() as conn:
        return int(
            conn.scalar(f"SELECT COUNT(*) AS total FROM pc_reports{where}", tuple(params))
            or 0
        )


def close_report(
    report_id: int,
    actor_id: str,
    actor_name: str,
    close_note: str = "",
) -> dict | None:
    supports_audit = report_closure_supported()
    with _connect() as conn:
        report = conn.query_one("SELECT * FROM pc_reports WHERE id = %s", (report_id,))
        if not report:
            return None
        if report.get("is_open"):
            if supports_audit:
                conn.execute(
                    """UPDATE pc_reports
                          SET is_open = 0, closed_at = %s, closed_by_id = %s,
                              closed_by_name = %s, close_note = %s
                        WHERE id = %s AND is_open = 1""",
                    (now_ms(), actor_id, actor_name, close_note or None, report_id),
                )
            else:
                conn.execute(
                    "UPDATE pc_reports SET is_open = 0 WHERE id = %s AND is_open = 1",
                    (report_id,),
                )
        return conn.query_one("SELECT * FROM pc_reports WHERE id = %s", (report_id,))


def add_player_note(
    player_uuid: str,
    note: str,
    category: str,
    author_id: str,
    author_name: str,
) -> dict:
    if not moderation_notes_supported():
        raise MinecraftDatabaseUnavailable(
            "Spielernotizen sind noch nicht verfügbar. Starte PumpeDatabase mit Migration V5."
        )
    created_at = now_ms()
    with _connect() as conn:
        conn.execute(
            """INSERT INTO pc_player_notes
                   (player_uuid, note, category, author_id, author_name, created_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (player_uuid, note, category, author_id, author_name, created_at),
        )
        note_id = conn.scalar("SELECT LAST_INSERT_ID() AS id")
        return conn.query_one(
            "SELECT * FROM pc_player_notes WHERE id = %s", (note_id,)
        ) or {}


# ══════════ Punishments (bans) ══════════


def _punishments_where(
    q: str = "", status: str = "all", punishment_type: str = ""
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status == "active":
        clauses.append(f"(expires_at IS NULL OR expires_at > %s){_not_revoked()}")
        params.append(now_ms())
    elif status == "expired":
        clauses.append(f"(expires_at IS NOT NULL AND expires_at <= %s){_not_revoked()}")
        params.append(now_ms())
    elif status == "permanent":
        clauses.append(f"expires_at IS NULL{_not_revoked()}")
    elif status == "revoked":
        # Ohne Migration V3 kann es keine aufgehobenen Bans geben.
        clauses.append("revoked_at IS NOT NULL" if lifecycle_supported() else "1 = 0")
    if punishment_type:
        clauses.append("punishment_type = %s")
        params.append(punishment_type)
    if q:
        like = f"%{q}%"
        clauses.append(
            "(target_name LIKE %s OR staff_name LIKE %s OR reason LIKE %s"
            " OR target_uuid LIKE %s OR punishment_id LIKE %s)"
        )
        params.extend([like] * 5)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_punishments(
    q: str = "",
    status: str = "all",
    punishment_type: str = "",
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    where, params = _punishments_where(q, status, punishment_type)
    with _connect() as conn:
        return conn.query(
            f"SELECT * FROM pc_punishments{where} ORDER BY created_at DESC"
            " LIMIT %s OFFSET %s",
            tuple([*params, limit, offset]),
        )


def count_punishments(
    q: str = "", status: str = "all", punishment_type: str = ""
) -> int:
    where, params = _punishments_where(q, status, punishment_type)
    with _connect() as conn:
        return int(
            conn.scalar(
                f"SELECT COUNT(*) AS total FROM pc_punishments{where}", tuple(params)
            )
            or 0
        )


def list_punishment_types() -> list[str]:
    with _connect() as conn:
        rows = conn.query(
            "SELECT DISTINCT punishment_type FROM pc_punishments ORDER BY punishment_type"
        )
    return [row["punishment_type"] for row in rows if row.get("punishment_type")]


# ══════════ Mutes ══════════


def _mutes_where(q: str = "", status: str = "all") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status == "active":
        clauses.append(f"expires_at > %s{_not_unmuted()}")
        params.append(now_ms())
    elif status == "expired":
        clauses.append(f"expires_at <= %s{_not_unmuted()}")
        params.append(now_ms())
    elif status == "lifted":
        # Ohne Migration V3 kann es keine aufgehobenen Mutes geben.
        clauses.append("unmuted_at IS NOT NULL" if lifecycle_supported() else "1 = 0")
    if q:
        like = f"%{q}%"
        clauses.append(
            "(target_name LIKE %s OR staff_name LIKE %s OR reason LIKE %s OR target_uuid LIKE %s)"
        )
        params.extend([like] * 4)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_mutes(
    q: str = "", status: str = "all", limit: int = 25, offset: int = 0
) -> list[dict]:
    where, params = _mutes_where(q, status)
    with _connect() as conn:
        return conn.query(
            f"SELECT * FROM pc_mutes{where} ORDER BY muted_at DESC LIMIT %s OFFSET %s",
            tuple([*params, limit, offset]),
        )


def count_mutes(q: str = "", status: str = "all") -> int:
    where, params = _mutes_where(q, status)
    with _connect() as conn:
        return int(
            conn.scalar(f"SELECT COUNT(*) AS total FROM pc_mutes{where}", tuple(params))
            or 0
        )


# ══════════ Warnings ══════════


def _warnings_where(q: str = "") -> tuple[str, list[Any]]:
    if not q:
        return "", []
    like = f"%{q}%"
    return (
        " WHERE (target_name LIKE %s OR staff_name LIKE %s OR reason LIKE %s"
        " OR target_uuid LIKE %s)",
        [like] * 4,
    )


def list_warnings(q: str = "", limit: int = 25, offset: int = 0) -> list[dict]:
    where, params = _warnings_where(q)
    with _connect() as conn:
        return conn.query(
            f"SELECT * FROM pc_warnings{where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple([*params, limit, offset]),
        )


def count_warnings(q: str = "") -> int:
    where, params = _warnings_where(q)
    with _connect() as conn:
        return int(
            conn.scalar(
                f"SELECT COUNT(*) AS total FROM pc_warnings{where}", tuple(params)
            )
            or 0
        )


# ══════════ Overview leaderboards / activity ══════════


def get_top_playtime(limit: int = 5) -> list[dict]:
    with _connect() as conn:
        rows = conn.query(
            """SELECT player_uuid, total_seconds, active_seconds, afk_seconds, updated_at
                 FROM pc_playtime
                ORDER BY total_seconds DESC
                LIMIT %s""",
            (limit,),
        )
        names = resolve_names(conn, [row["player_uuid"] for row in rows])
    return [decorate_player(row, "player_uuid", names) for row in rows]


def get_top_deaths(limit: int = 5) -> list[dict]:
    with _connect() as conn:
        rows = conn.query(
            """SELECT player_uuid, death_count, updated_at
                 FROM pc_death_counts
                ORDER BY death_count DESC
                LIMIT %s""",
            (limit,),
        )
        names = resolve_names(conn, [row["player_uuid"] for row in rows])
    return [decorate_player(row, "player_uuid", names) for row in rows]


def get_recent_moderation(limit: int = 6) -> list[dict]:
    """Newest bans, mutes and warnings merged into one activity feed."""
    with _connect() as conn:
        punishments = conn.query(
            """SELECT punishment_id, punishment_type, target_uuid, target_name,
                      staff_name, reason, created_at, expires_at
                 FROM pc_punishments ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )
        mutes = conn.query(
            """SELECT target_uuid, target_name, staff_name, reason,
                      muted_at AS created_at, expires_at
                 FROM pc_mutes ORDER BY muted_at DESC LIMIT %s""",
            (limit,),
        )
        warnings = conn.query(
            """SELECT target_uuid, target_name, staff_name, reason, created_at
                 FROM pc_warnings ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )

    feed: list[dict] = []
    for row in punishments:
        feed.append({**row, "kind": "ban", "kind_label": row.get("punishment_type") or "BAN"})
    for row in mutes:
        feed.append({**row, "kind": "mute", "kind_label": "MUTE"})
    for row in warnings:
        feed.append({**row, "kind": "warning", "kind_label": "WARN"})
    feed.sort(key=lambda row: int(row.get("created_at") or 0), reverse=True)
    return feed[:limit]


def get_recent_reports(limit: int = 6) -> list[dict]:
    with _connect() as conn:
        return conn.query(
            """SELECT * FROM pc_reports ORDER BY is_open DESC, created_at DESC LIMIT %s""",
            (limit,),
        )


# ══════════ Chat Control ══════════

CHAT_SORTS = {
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
    "player_asc": "player_name ASC, created_at DESC",
    "player_desc": "player_name DESC, created_at DESC",
    "message_asc": "message ASC, created_at DESC",
    "message_desc": "message DESC, created_at DESC",
    "type_asc": "message_type ASC, created_at DESC",
    "type_desc": "message_type DESC, created_at DESC",
}


def chat_messages_supported() -> bool:
    return _table_supported("pc_chat_messages")


def get_chat_stats() -> dict:
    if not chat_messages_supported():
        return {"total": 0, "global": 0, "msg": 0, "deleted": 0}
    with _connect() as conn:
        row = conn.query_one(
            """SELECT COUNT(*) AS total,
                      SUM(message_type = 'GLOBAL') AS global_count,
                      SUM(message_type = 'MSG') AS msg_count,
                      SUM(deleted_at IS NOT NULL) AS deleted_count
                 FROM pc_chat_messages
                WHERE blocked = 0"""
        ) or {}
    return {
        "total": int(row.get("total") or 0),
        "global": int(row.get("global_count") or 0),
        "msg": int(row.get("msg_count") or 0),
        "deleted": int(row.get("deleted_count") or 0),
    }


def _chat_where(
    q: str, message_type: str, search_field: str = "all"
) -> tuple[str, list[Any]]:
    clauses = ["blocked = 0"]
    params: list[Any] = []
    normalized_type = message_type.upper()
    if normalized_type in {"GLOBAL", "MSG"}:
        clauses.append("message_type = %s")
        params.append(normalized_type)
    if q:
        like = f"%{q}%"
        if search_field == "uuid":
            clauses.append("(player_uuid LIKE %s OR recipient_uuid LIKE %s)")
            params.extend([like, like])
        elif search_field == "username":
            clauses.append("(player_name LIKE %s OR recipient_name LIKE %s)")
            params.extend([like, like])
        elif search_field == "message":
            clauses.append("message LIKE %s")
            params.append(like)
        else:
            clauses.append(
                "(player_name LIKE %s OR player_uuid LIKE %s OR message LIKE %s"
                " OR recipient_name LIKE %s OR recipient_uuid LIKE %s)"
            )
            params.extend([like] * 5)
    return " WHERE " + " AND ".join(clauses), params


def list_chat_messages(
    q: str = "",
    message_type: str = "all",
    search_field: str = "all",
    sort: str = "newest",
    limit: int = 25,
    offset: int = 0,
) -> list[dict]:
    if not chat_messages_supported():
        return []
    where, params = _chat_where(q, message_type, search_field)
    order = CHAT_SORTS.get(sort, CHAT_SORTS["newest"])
    with _connect() as conn:
        return conn.query(
            f"SELECT * FROM pc_chat_messages{where} ORDER BY {order} LIMIT %s OFFSET %s",
            tuple([*params, limit, offset]),
        )


def count_chat_messages(
    q: str = "", message_type: str = "all", search_field: str = "all"
) -> int:
    if not chat_messages_supported():
        return 0
    where, params = _chat_where(q, message_type, search_field)
    with _connect() as conn:
        return int(
            conn.scalar(
                f"SELECT COUNT(*) AS total FROM pc_chat_messages{where}", tuple(params)
            ) or 0
        )


def get_recent_chat_messages(limit: int = 6) -> list[dict]:
    return list_chat_messages(limit=limit, offset=0)


# ══════════ Skills ══════════

# Reihenfolge und Farben spiegeln das PumpeSkills-Plugin. Die Hex-Werte sind auf
# der Panel-Kartenfläche (#0d1320) validiert: benachbarte Paare halten
# CVD ΔE 13.0 (Ziel 8) und Normalsicht ΔE 19.3 (Floor 15) ein.
SKILLS: list[dict] = [
    {
        "id": "fischer",
        "name": "Fischer",
        "color": "#199e70",
        "icon": "🎣",
        "description": "Angeln und seltene Fänge",
    },
    {
        "id": "miner",
        "name": "Miner",
        "color": "#3987e5",
        "icon": "⛏️",
        "description": "Stein und Erze abbauen",
    },
    {
        "id": "mobs",
        "name": "Mobs",
        "color": "#e66767",
        "icon": "⚔️",
        "description": "Monster und Tiere besiegen",
    },
    {
        "id": "builder",
        "name": "Builder",
        "color": "#9085e9",
        "icon": "🧱",
        "description": "Blöcke platzieren",
    },
    {
        "id": "dorf",
        "name": "Dorf",
        "color": "#008300",
        "icon": "🏡",
        "description": "Handeln mit Villagern",
    },
    {
        "id": "tierfreund",
        "name": "Tierfreund",
        "color": "#d55181",
        "icon": "🐾",
        "description": "Tiere zähmen",
    },
    {
        "id": "farmer",
        "name": "Farmer",
        "color": "#c98500",
        "icon": "🌾",
        "description": "Ernten, Holz, Erde und Ackerland",
    },
]

SKILLS_BY_ID = {skill["id"]: skill for skill in SKILLS}

SKILL_SCORE_KEY = "score"
SKILL_MAX_LEVEL = 100
_SKILL_LEVEL_BASE = 50
DEFAULT_SKILL_REWARDS = (
    {"level": 10, "label": "4 Smaragde"},
    {"level": 20, "label": "8 Smaragde"},
    {"level": 30, "label": "2 Diamanten"},
    {"level": 40, "label": "8 Erfahrungsfläschchen"},
    {"level": 50, "label": "4 Diamanten"},
    {"level": 60, "label": "16 Erfahrungsfläschchen"},
    {"level": 70, "label": "1 Netherit-Schrott"},
    {"level": 80, "label": "1 verzauberter goldener Apfel"},
    {"level": 90, "label": "2 Netherit-Schrott"},
    {"level": 100, "label": "1 Netheritbarren"},
)
_skill_rewards_lock = threading.Lock()
_skill_rewards_cache: tuple[float, tuple[dict, ...]] = (0.0, DEFAULT_SKILL_REWARDS)


def get_skill_rewards() -> tuple[dict, ...]:
    global _skill_rewards_cache
    expires_at, cached = _skill_rewards_cache
    now = time.monotonic()
    if now < expires_at:
        return cached
    with _skill_rewards_lock:
        expires_at, cached = _skill_rewards_cache
        if now < expires_at:
            return cached
        rewards = DEFAULT_SKILL_REWARDS
        try:
            if _table_supported("pc_skill_reward_definitions"):
                with _connect() as conn:
                    rows = conn.query(
                        """SELECT milestone_level, label
                             FROM pc_skill_reward_definitions
                            ORDER BY milestone_level"""
                    )
                rewards = tuple(
                    {"level": int(row["milestone_level"]), "label": row["label"]}
                    for row in rows
                )
        except MinecraftDatabaseUnavailable:
            logger.warning("Could not refresh skill reward definitions.", exc_info=True)
        _skill_rewards_cache = (now + 60.0, rewards)
        return rewards

# Detailzähler je Skill – Beschriftung, Schlüssel und das Präfix, aus dem die
# Top-Einträge kommen. Deckungsgleich mit SkillsCommand im Plugin.
SKILL_DETAILS: dict[str, dict] = {
    "fischer": {
        "top_prefix": "item.",
        "top_label": "Häufigste Fänge",
        "lines": [
            ("Fänge gesamt", "caught"),
            ("Fische", "fish"),
            ("Schätze", "treasure"),
            ("Müll", "junk"),
        ],
    },
    "miner": {
        "top_prefix": "ore.",
        "top_label": "Meiste Erze",
        "lines": [
            ("Blöcke abgebaut", "blocks"),
            ("Stein", "stone"),
            ("Erze", "ore"),
        ],
    },
    "mobs": {
        "top_prefix": "mob.",
        "top_label": "Meiste Kills",
        "lines": [
            ("Kills gesamt", "kills"),
            ("Monster", "monster"),
            ("Tiere", "animal"),
            ("Bosse", "boss"),
        ],
    },
    "builder": {
        "top_prefix": "block.",
        "top_label": "Meistgenutzte Blöcke",
        "lines": [("Blöcke platziert", "placed")],
    },
    "dorf": {
        "top_prefix": "trade.",
        "top_label": "Häufigste Trades",
        "lines": [
            ("Handel", "trades"),
            ("Villager", "villagers"),
            ("Smaragde gezahlt", "emeralds"),
            ("Günstigster Handel", "best_price"),
        ],
    },
    "tierfreund": {
        "top_prefix": "pet.",
        "top_label": "Meiste Tiere",
        "lines": [("Gezähmt", "tamed")],
    },
    "farmer": {
        "top_prefix": "crop.",
        "top_label": "Meiste Ernte",
        "lines": [
            ("Ernten", "crops"),
            ("Abgepflückt", "harvested"),
            ("Holz", "logs"),
            ("Erde", "dirt"),
            ("Ackerland", "farmland"),
        ],
    },
}

_skills_lock = threading.Lock()
_skills_supported: bool | None = None


def skills_supported() -> bool:
    """pc_skill_stats kommt mit Migration V4 des Plugins."""
    global _skills_supported
    if _skills_supported is None:
        with _skills_lock:
            if _skills_supported is None:
                with _connect() as conn:
                    rows = conn.query(
                        """SELECT TABLE_NAME
                             FROM INFORMATION_SCHEMA.TABLES
                            WHERE TABLE_SCHEMA = DATABASE()
                              AND TABLE_NAME = 'pc_skill_stats'"""
                    )
                _skills_supported = bool(rows)
    return _skills_supported


# ── Levelkurve (identisch zu SkillLevel.java) ──


def skill_level(score: Any) -> int:
    value = int(score or 0)
    if value < _SKILL_LEVEL_BASE:
        return 1
    level = int((value / _SKILL_LEVEL_BASE) ** 0.5) + 1
    return max(1, min(SKILL_MAX_LEVEL, level))


def skill_score_for_level(level: int) -> int:
    steps = max(0, level - 1)
    return _SKILL_LEVEL_BASE * steps * steps


def skill_score_to_next(score: Any) -> int:
    value = int(score or 0)
    level = skill_level(value)
    if level >= SKILL_MAX_LEVEL:
        return 0
    return max(0, skill_score_for_level(level + 1) - value)


def skill_progress(score: Any) -> float:
    value = int(score or 0)
    level = skill_level(value)
    if level >= SKILL_MAX_LEVEL:
        return 1.0
    start = skill_score_for_level(level)
    end = skill_score_for_level(level + 1)
    if end <= start:
        return 1.0
    return max(0.0, min(1.0, (value - start) / (end - start)))


def skill_level_details(score: Any) -> dict:
    value = max(0, int(score or 0))
    level = skill_level(value)
    if level >= SKILL_MAX_LEVEL:
        return {
            "level": level,
            "progress": 1.0,
            "progress_percent": 100.0,
            "level_score": 0,
            "level_target": 0,
            "to_next": 0,
            "next_level": None,
            "next_reward": None,
        }
    start = skill_score_for_level(level)
    target = skill_score_for_level(level + 1)
    progress = skill_progress(value)
    return {
        "level": level,
        "progress": progress,
        "progress_percent": round(progress * 100, 1),
        "level_score": max(0, value - start),
        "level_target": max(0, target - start),
        "to_next": max(0, target - value),
        "next_level": level + 1,
        "next_reward": next(
            (reward for reward in get_skill_rewards() if reward["level"] > level), None
        ),
    }


# ── Abfragen ──


def get_skills_overview() -> dict:
    """Serverweite Kennzahlen plus Spitzenreiter je Skill."""
    with _connect() as conn:
        totals = conn.query(
            """SELECT skill,
                      SUM(amount) AS total_score,
                      COUNT(*) AS players,
                      MAX(amount) AS best_score
                 FROM pc_skill_stats
                WHERE stat_key = %s AND amount > 0
                GROUP BY skill""",
            (SKILL_SCORE_KEY,),
        )
        leaders = conn.query(
            """SELECT skill, player_uuid, player_name, amount
                 FROM (
                     SELECT s.skill,
                            s.player_uuid,
                            p.player_name,
                            s.amount,
                            ROW_NUMBER() OVER (
                                PARTITION BY s.skill ORDER BY s.amount DESC, s.player_uuid ASC
                            ) AS position
                       FROM pc_skill_stats s
                       LEFT JOIN pc_players p ON p.player_uuid = s.player_uuid
                      WHERE s.stat_key = %s AND s.amount > 0
                 ) ranked
                WHERE position = 1""",
            (SKILL_SCORE_KEY,),
        )
        tracked_players = conn.scalar(
            """SELECT COUNT(DISTINCT player_uuid) AS total
                 FROM pc_skill_stats
                WHERE stat_key = %s AND amount > 0""",
            (SKILL_SCORE_KEY,),
        )

    totals_by_skill = {row["skill"]: row for row in totals}
    leaders_by_skill = {row["skill"]: row for row in leaders}

    cards = []
    total_score = 0
    for skill in SKILLS:
        row = totals_by_skill.get(skill["id"]) or {}
        leader = leaders_by_skill.get(skill["id"]) or {}
        score = int(row.get("total_score") or 0)
        total_score += score
        best = int(leader.get("amount") or 0)
        cards.append(
            {
                **skill,
                "total_score": score,
                "players": int(row.get("players") or 0),
                "leader_name": leader.get("player_name")
                or (str(leader.get("player_uuid") or "")[:8] or None),
                "leader_uuid": leader.get("player_uuid"),
                "leader_score": best,
                **{f"leader_{key}": value for key, value in skill_level_details(best).items()},
            }
        )

    return {
        "cards": cards,
        "total_score": total_score,
        "tracked_players": int(tracked_players or 0),
        "top_skill": max(cards, key=lambda card: card["total_score"]) if cards else None,
    }


def count_skill_leaderboard(skill_id: str) -> int:
    with _connect() as conn:
        return int(
            conn.scalar(
                """SELECT COUNT(*) AS total
                     FROM pc_skill_stats
                    WHERE skill = %s AND stat_key = %s AND amount > 0""",
                (skill_id, SKILL_SCORE_KEY),
            )
            or 0
        )


def list_skill_leaderboard(skill_id: str, limit: int = 25, offset: int = 0) -> list[dict]:
    with _connect() as conn:
        rows = conn.query(
            """SELECT s.player_uuid, s.amount, p.player_name
                 FROM pc_skill_stats s
                 LEFT JOIN pc_players p ON p.player_uuid = s.player_uuid
                WHERE s.skill = %s AND s.stat_key = %s AND s.amount > 0
                ORDER BY s.amount DESC, p.player_name ASC
                LIMIT %s OFFSET %s""",
            (skill_id, SKILL_SCORE_KEY, limit, offset),
        )
        names = resolve_names(
            conn, [row["player_uuid"] for row in rows if not row.get("player_name")]
        )

    result = []
    for index, row in enumerate(rows, start=offset + 1):
        score = int(row["amount"] or 0)
        result.append(
            {
                "rank": index,
                "player_uuid": row["player_uuid"],
                "player_name": row.get("player_name")
                or names.get(row["player_uuid"])
                or str(row["player_uuid"])[:8],
                "player_head_url": head_url(row["player_uuid"]),
                "score": score,
                **skill_level_details(score),
            }
        )
    return result


def get_skill_top_stats(skill_id: str, limit: int = 8) -> list[dict]:
    """Serverweit häufigste Detaileinträge eines Skills, z. B. meistabgebaute Erze."""
    detail = SKILL_DETAILS.get(skill_id)
    if not detail:
        return []
    with _connect() as conn:
        rows = conn.query(
            """SELECT stat_key, SUM(amount) AS total
                 FROM pc_skill_stats
                WHERE skill = %s AND stat_key LIKE %s AND amount > 0
                GROUP BY stat_key
                ORDER BY total DESC
                LIMIT %s""",
            (skill_id, detail["top_prefix"] + "%", limit),
        )
    return [
        {
            "key": row["stat_key"],
            "label": _stat_label(detail["top_prefix"], row["stat_key"]),
            "total": int(row["total"] or 0),
        }
        for row in rows
    ]


def get_player_skills(player_uuid: str) -> list[dict]:
    """Alle Skills eines Spielers mit Level, Fortschritt und Platzierung."""
    with _connect() as conn:
        rows = conn.query(
            """SELECT skill, amount
                 FROM pc_skill_stats
                WHERE player_uuid = %s AND stat_key = %s""",
            (player_uuid, SKILL_SCORE_KEY),
        )
        scores = {row["skill"]: int(row["amount"] or 0) for row in rows}
        ranks = conn.query(
            """SELECT s.skill,
                      (SELECT COUNT(*) + 1
                         FROM pc_skill_stats o
                        WHERE o.skill = s.skill
                          AND o.stat_key = s.stat_key
                          AND o.amount > s.amount) AS position
                 FROM pc_skill_stats s
                WHERE s.player_uuid = %s AND s.stat_key = %s AND s.amount > 0""",
            (player_uuid, SKILL_SCORE_KEY),
        )
    ranks_by_skill = {row["skill"]: int(row["position"] or 0) for row in ranks}

    result = []
    for skill in SKILLS:
        score = scores.get(skill["id"], 0)
        result.append(
            {
                **skill,
                "score": score,
                **skill_level_details(score),
                "rank": ranks_by_skill.get(skill["id"]) or None,
            }
        )
    return result


def get_player_skill_stats(player_uuid: str, skill_id: str) -> dict:
    """Detailzähler eines Spielers in einem Skill inklusive Top-Einträgen."""
    detail = SKILL_DETAILS.get(skill_id)
    if not detail:
        return {"lines": [], "top": []}

    with _connect() as conn:
        rows = conn.query(
            """SELECT stat_key, amount
                 FROM pc_skill_stats
                WHERE player_uuid = %s AND skill = %s""",
            (player_uuid, skill_id),
        )
    values = {row["stat_key"]: int(row["amount"] or 0) for row in rows}

    top = sorted(
        (
            {
                "key": key,
                "label": _stat_label(detail["top_prefix"], key),
                "total": amount,
            }
            for key, amount in values.items()
            if key.startswith(detail["top_prefix"]) and amount > 0
        ),
        key=lambda entry: entry["total"],
        reverse=True,
    )[:5]

    return {
        "lines": [
            {"label": label, "value": values.get(key, 0)}
            for label, key in detail["lines"]
        ],
        "top": top,
        "top_label": detail["top_label"],
    }


def _stat_label(prefix: str, stat_key: str) -> str:
    """Macht aus 'ore.deepslate_diamond_ore' ein lesbares 'Deepslate Diamond Ore'."""
    suffix = stat_key[len(prefix):] if stat_key.startswith(prefix) else stat_key
    return suffix.replace("_", " ").title()
