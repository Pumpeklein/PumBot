from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

try:
    from .config import (
        BASE_DIR,
        Config,
        ensure_dirs,
        DEFAULT_GUILD_ID,
        DEFAULT_ADMIN_ROLE_ID,
    )
    from .datetime_format import berlin_today
except ImportError:
    from config import (
        BASE_DIR,
        Config,
        ensure_dirs,
        DEFAULT_GUILD_ID,
        DEFAULT_ADMIN_ROLE_ID,
    )
    from datetime_format import berlin_today


class DatabaseConnection:
    def __init__(self) -> None:
        missing = [
            name
            for name, value in {
                "DB_NAME": Config.DB_NAME,
                "DB_USER": Config.DB_USER,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Datenbank-Konfiguration fehlt: "
                + ", ".join(missing)
                + ". Setze DB_HOST, DB_PORT, DB_NAME, DB_USER und DB_PASSWORD in der .env."
            )
        self.conn = pymysql.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database=Config.DB_NAME,
            charset=Config.DB_CHARSET,
            cursorclass=DictCursor,
            autocommit=False,
        )

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            self.conn.rollback()
        self.conn.close()

    def _sql(self, sql: str) -> str:
        return (
            sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
            .replace("COLLATE NOCASE", "")
            .replace("?", "%s")
        )

    def _param(self, value: Any) -> Any:
        if isinstance(value, str) and "T" in value and ":" in value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                return value
        return value

    def _params(self, params: Any) -> Any:
        if params is None:
            return None
        if isinstance(params, dict):
            return {key: self._param(value) for key, value in params.items()}
        return tuple(self._param(value) for value in params)

    def execute(self, sql: str, params: Any = None):
        cursor = self.conn.cursor()
        cursor.execute(self._sql(sql), self._params(params))
        return cursor

    def executescript(self, sql: str) -> None:
        for statement in sql.split(";"):
            statement = statement.strip()
            if not statement:
                continue
            try:
                self.execute(statement)
            except pymysql.err.OperationalError as exc:
                if exc.args and exc.args[0] in {
                    1061,  # duplicate key name
                    1072,  # key column does not exist yet; later _ensure_columns handles migrations
                }:
                    continue
                raise

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()


def _connect() -> DatabaseConnection:
    ensure_dirs()
    return DatabaseConnection()


def init_db() -> None:
    schema_path = BASE_DIR / "models_mysql.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with _connect() as conn:
        conn.executescript(sql)
        _ensure_columns(
            conn,
            "guild_members",
            {
                "roles_json": "TEXT",
                "banner_url": "TEXT",
                "accent_color": "INT",
                "locale": "VARCHAR(32)",
                "presence_status": "TEXT",
                "activity_name": "TEXT",
                "activity_type": "TEXT",
                "status_updated_at": "TEXT",
            },
        )
        _ensure_columns(
            conn,
            "guild_member_name_history",
            {
                "changed_by_id": "VARCHAR(32)",
                "changed_by_name": "VARCHAR(255)",
            },
        )
        _ensure_columns(
            conn,
            "users",
            {
                "discord_banner": "TEXT",
                "accent_color": "INT",
                "locale": "VARCHAR(32)",
            },
        )
        _ensure_columns(
            conn,
            "guild_messages",
            {
                "original_content": "TEXT",
                "channel_type": "VARCHAR(32)",
                "parent_channel_id": "VARCHAR(32)",
                "attachment_urls_json": "LONGTEXT",
            },
        )
        _ensure_columns(
            conn,
            "guild_message_history",
            {
                "attachment_urls_json": "LONGTEXT",
            },
        )
        _ensure_columns(
            conn,
            "discord_log_entries",
            {
                "channel_name": "VARCHAR(255)",
                "author_id": "VARCHAR(32)",
                "author_name": "VARCHAR(255)",
                "actor_id": "VARCHAR(32)",
                "actor_name": "VARCHAR(255)",
                "event_title": "VARCHAR(255)",
                "event_summary": "TEXT",
                "content": "LONGTEXT",
                "embed_count": "INT NOT NULL DEFAULT 0",
                "attachment_count": "INT NOT NULL DEFAULT 0",
                "jump_url": "TEXT",
                "edited_at": "DATETIME NULL",
            },
        )
        conn.commit()
    _seed_default_roles()
    _seed_default_bot_messages()


def _table_columns(conn: DatabaseConnection, table: str) -> set[str]:
    rows = conn.execute(
        """SELECT COLUMN_NAME
           FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
        (table,),
    ).fetchall()
    return {row["COLUMN_NAME"] for row in rows}


def _ensure_columns(
    conn: DatabaseConnection, table: str, columns: dict[str, str]
) -> None:
    existing = _table_columns(conn, table)
    for name, definition in columns.items():
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            except pymysql.err.OperationalError as exc:
                if not exc.args or exc.args[0] != 1060:
                    raise


def _seed_default_roles() -> None:
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM roles WHERE guild_id = ? AND discord_role_id = ?",
            (DEFAULT_GUILD_ID, DEFAULT_ADMIN_ROLE_ID),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO roles (guild_id, discord_role_id, role_name, permissions) VALUES (?, ?, ?, ?)",
                (DEFAULT_GUILD_ID, DEFAULT_ADMIN_ROLE_ID, "Admin", '["admin"]'),
            )
            conn.commit()


def _seed_default_bot_messages() -> None:
    with _connect() as conn:
        message_rows = conn.execute(
            """SELECT guild_id, config_value
               FROM guild_config
               WHERE config_key = 'birthday_list_message_id'"""
        ).fetchall()
        for row in message_rows:
            guild_id = row["guild_id"]
            message_id = row["config_value"]
            if not guild_id or not message_id:
                continue
            existing = conn.execute(
                """SELECT 1
                   FROM bot_messages
                   WHERE guild_id = ? AND message_type = 'birthday_list'
                   LIMIT 1""",
                (guild_id,),
            ).fetchone()
            if existing:
                continue
            channel_row = conn.execute(
                """SELECT config_value
                   FROM guild_config
                   WHERE guild_id = ? AND config_key = 'birthday_list_channel_id'""",
                (guild_id,),
            ).fetchone()
            channel_id = channel_row["config_value"] if channel_row else None
            conn.execute(
                """INSERT INTO bot_messages (guild_id, message_type, message_id, channel_id, meta_key)
                   VALUES (?, ?, ?, ?, ?)
                   ON DUPLICATE KEY UPDATE
                     channel_id = COALESCE(VALUES(channel_id), channel_id),
                     updated_at = CURRENT_TIMESTAMP""",
                (guild_id, "birthday_list", message_id, channel_id, "birthdays"),
            )
        conn.commit()


def get_birthdays_panel_guild_id(default_guild_id: str) -> str:
    with _connect() as conn:
        has_default = conn.execute(
            """SELECT 1
               FROM birthdays
               WHERE guild_id = ?
               UNION
               SELECT 1
               FROM guild_config
               WHERE guild_id = ? AND config_key LIKE ?
               UNION
               SELECT 1
               FROM bot_messages
               WHERE guild_id = ? AND message_type = 'birthday_list'
               LIMIT 1""",
            (default_guild_id, default_guild_id, "birthday_%", default_guild_id),
        ).fetchone()
        if has_default:
            return default_guild_id

        row = conn.execute(
            """SELECT guild_id
               FROM birthdays
               GROUP BY guild_id
               ORDER BY COUNT(*) DESC, guild_id ASC
               LIMIT 1"""
        ).fetchone()
        if row:
            return row["guild_id"]

        row = conn.execute(
            """SELECT guild_id
               FROM guild_config
               WHERE config_key LIKE ?
               ORDER BY guild_id ASC
               LIMIT 1""",
            ("birthday_%",),
        ).fetchone()
        if row:
            return row["guild_id"]

        row = conn.execute(
            """SELECT guild_id
               FROM bot_messages
               WHERE message_type = 'birthday_list'
               ORDER BY guild_id ASC
               LIMIT 1"""
        ).fetchone()
        if row:
            return row["guild_id"]

        return default_guild_id


def get_guild_members_panel_guild_id(default_guild_id: str) -> str:
    with _connect() as conn:
        has_default = conn.execute(
            """SELECT 1
               FROM guild_members
               WHERE guild_id = ?
               LIMIT 1""",
            (default_guild_id,),
        ).fetchone()
        if has_default:
            return default_guild_id

        row = conn.execute(
            """SELECT guild_id
               FROM guild_members
               GROUP BY guild_id
               ORDER BY
                 SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) DESC,
                 COUNT(*) DESC,
                 guild_id ASC
               LIMIT 1"""
        ).fetchone()
        if row:
            return row["guild_id"]

        return default_guild_id


# ══════════ Users (Discord OAuth2) ══════════


def upsert_user(
    discord_id: str,
    discord_username: str,
    discord_avatar: str | None = None,
    discord_banner: str | None = None,
    accent_color: int | None = None,
    locale: str | None = None,
) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO users (
                 discord_id, discord_username, discord_avatar, discord_banner,
                 accent_color, locale, last_login
               ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON DUPLICATE KEY UPDATE
                 discord_username = VALUES(discord_username),
                 discord_avatar = VALUES(discord_avatar),
                 discord_banner = COALESCE(VALUES(discord_banner), discord_banner),
                 accent_color = COALESCE(VALUES(accent_color), accent_color),
                 locale = COALESCE(VALUES(locale), locale),
                 last_login = CURRENT_TIMESTAMP""",
            (
                discord_id,
                discord_username,
                discord_avatar,
                discord_banner,
                accent_color,
                locale,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return dict(row)


def get_user_by_discord_id(discord_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY last_login DESC").fetchall()
        return [dict(r) for r in rows]


def replace_user_connections(
    discord_id: str, connections: list[dict[str, Any]]
) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM user_connections WHERE discord_id = ?", (discord_id,))
        for item in connections:
            connection_id = str(item.get("id") or "").strip()
            connection_type = str(item.get("type") or "").strip()
            name = str(item.get("name") or "").strip()
            if not connection_id or not connection_type or not name:
                continue
            show_activity = item.get("show_activity")
            two_way_link = item.get("two_way_link")
            conn.execute(
                """INSERT INTO user_connections (
                     discord_id, connection_id, connection_type, name, verified,
                     visibility, show_activity, two_way_link, metadata_json, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    discord_id,
                    connection_id,
                    connection_type,
                    name,
                    1 if item.get("verified") else 0,
                    item.get("visibility"),
                    1 if show_activity else 0 if show_activity is not None else None,
                    1 if two_way_link else 0 if two_way_link is not None else None,
                    json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                ),
            )
        conn.commit()


def list_user_connections(discord_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT *
               FROM user_connections
               WHERE discord_id = ?
               ORDER BY connection_type ASC, name ASC""",
            (discord_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _member_name_changed(existing: dict[str, Any], member: dict[str, Any]) -> bool:
    return any(
        (existing[key] or "") != (member.get(key) or "")
        for key in ("username", "global_name", "display_name")
    )


def upsert_guild_member(guild_id: str, member: dict[str, Any]) -> dict:
    user_id = str(member["user_id"])
    username = str(member.get("username") or user_id)
    display_name = str(
        member.get("display_name") or member.get("global_name") or username
    )
    global_name = member.get("global_name")
    discriminator = member.get("discriminator")
    avatar_url = member.get("avatar_url")
    banner_url = member.get("banner_url")
    accent_color = member.get("accent_color")
    locale = member.get("locale")
    roles_json = json.dumps(member.get("roles") or [], ensure_ascii=False)
    is_bot = 1 if member.get("is_bot") else 0
    status = member.get("status") or "active"
    presence_status = member.get("presence_status")
    activity_name = member.get("activity_name")
    activity_type = member.get("activity_type")
    joined_at = member.get("joined_at")
    left_at = member.get("left_at")
    changed_by_id = member.get("changed_by_id")
    changed_by_name = member.get("changed_by_name")

    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM guild_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if existing and _member_name_changed(
            existing,
            {
                "username": username,
                "global_name": global_name,
                "display_name": display_name,
            },
        ):
            conn.execute(
                """INSERT INTO guild_member_name_history (
                     guild_id, user_id, old_username, old_global_name, old_display_name,
                     new_username, new_global_name, new_display_name,
                     changed_by_id, changed_by_name
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    user_id,
                    existing["username"],
                    existing["global_name"],
                    existing["display_name"],
                    username,
                    global_name,
                    display_name,
                    changed_by_id,
                    changed_by_name,
                ),
            )

        conn.execute(
            """INSERT INTO guild_members (
                 guild_id, user_id, username, global_name, display_name, discriminator,
                 avatar_url, banner_url, accent_color, locale, roles_json,
                 is_bot, status, presence_status, activity_name, activity_type,
                 status_updated_at, joined_at, left_at, first_seen_at,
                 last_seen_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, datetime('now'), datetime('now'), datetime('now'))
               ON DUPLICATE KEY UPDATE
                 username = VALUES(username),
                 global_name = VALUES(global_name),
                 display_name = VALUES(display_name),
                 discriminator = VALUES(discriminator),
                 avatar_url = VALUES(avatar_url),
                 banner_url = COALESCE(VALUES(banner_url), banner_url),
                 accent_color = COALESCE(VALUES(accent_color), accent_color),
                 locale = COALESCE(VALUES(locale), locale),
                 roles_json = VALUES(roles_json),
                 is_bot = VALUES(is_bot),
                 status = VALUES(status),
                 presence_status = COALESCE(VALUES(presence_status), presence_status),
                 activity_name = COALESCE(VALUES(activity_name), activity_name),
                 activity_type = COALESCE(VALUES(activity_type), activity_type),
                 status_updated_at = CASE
                   WHEN VALUES(presence_status) IS NOT NULL THEN CURRENT_TIMESTAMP
                   ELSE status_updated_at
                 END,
                 joined_at = COALESCE(VALUES(joined_at), joined_at),
                 left_at = VALUES(left_at),
                 last_seen_at = CURRENT_TIMESTAMP,
                 updated_at = CURRENT_TIMESTAMP""",
            (
                guild_id,
                user_id,
                username,
                global_name,
                display_name,
                discriminator,
                avatar_url,
                banner_url,
                accent_color,
                locale,
                roles_json,
                is_bot,
                status,
                presence_status,
                activity_name,
                activity_type,
                joined_at,
                left_at,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM guild_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return dict(row)


def sync_guild_members(
    guild_id: str, members: list[dict[str, Any]], mark_missing_left: bool = True
) -> dict:
    seen_ids = {str(member["user_id"]) for member in members if member.get("user_id")}
    with _connect() as conn:
        for member in members:
            member = {**member, "status": "active", "left_at": None}
            user_id = str(member["user_id"])
            username = str(member.get("username") or user_id)
            display_name = str(
                member.get("display_name") or member.get("global_name") or username
            )
            existing = conn.execute(
                "SELECT * FROM guild_members WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            if existing and _member_name_changed(
                existing,
                {
                    "username": username,
                    "global_name": member.get("global_name"),
                    "display_name": display_name,
                },
            ):
                conn.execute(
                    """INSERT INTO guild_member_name_history (
                         guild_id, user_id, old_username, old_global_name, old_display_name,
                         new_username, new_global_name, new_display_name,
                         changed_by_id, changed_by_name
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        guild_id,
                        user_id,
                        existing["username"],
                        existing["global_name"],
                        existing["display_name"],
                        username,
                        member.get("global_name"),
                        display_name,
                        member.get("changed_by_id"),
                        member.get("changed_by_name"),
                    ),
                )
            conn.execute(
                """INSERT INTO guild_members (
                     guild_id, user_id, username, global_name, display_name, discriminator,
                     avatar_url, banner_url, accent_color, locale, roles_json,
                     is_bot, status, presence_status, activity_name, activity_type,
                     status_updated_at, joined_at, left_at, first_seen_at,
                     last_seen_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, datetime('now'), ?, NULL, datetime('now'), datetime('now'), datetime('now'))
                   ON DUPLICATE KEY UPDATE
                     username = VALUES(username),
                     global_name = VALUES(global_name),
                     display_name = VALUES(display_name),
                     discriminator = VALUES(discriminator),
                     avatar_url = VALUES(avatar_url),
                     banner_url = COALESCE(VALUES(banner_url), banner_url),
                     accent_color = COALESCE(VALUES(accent_color), accent_color),
                     locale = COALESCE(VALUES(locale), locale),
                     roles_json = VALUES(roles_json),
                     is_bot = VALUES(is_bot),
                     status = 'active',
                     presence_status = COALESCE(VALUES(presence_status), presence_status),
                     activity_name = COALESCE(VALUES(activity_name), activity_name),
                     activity_type = COALESCE(VALUES(activity_type), activity_type),
                     status_updated_at = CASE
                       WHEN VALUES(presence_status) IS NOT NULL THEN CURRENT_TIMESTAMP
                       ELSE status_updated_at
                     END,
                     joined_at = COALESCE(VALUES(joined_at), joined_at),
                     left_at = NULL,
                     last_seen_at = CURRENT_TIMESTAMP,
                     updated_at = CURRENT_TIMESTAMP""",
                (
                    guild_id,
                    user_id,
                    username,
                    member.get("global_name"),
                    display_name,
                    member.get("discriminator"),
                    member.get("avatar_url"),
                    member.get("banner_url"),
                    member.get("accent_color"),
                    member.get("locale"),
                    json.dumps(member.get("roles") or [], ensure_ascii=False),
                    1 if member.get("is_bot") else 0,
                    member.get("presence_status"),
                    member.get("activity_name"),
                    member.get("activity_type"),
                    member.get("joined_at"),
                ),
            )

        missing_ids: list[str] = []
        if mark_missing_left:
            active_before = conn.execute(
                "SELECT user_id FROM guild_members WHERE guild_id = ? AND status = 'active'",
                (guild_id,),
            ).fetchall()
            missing_ids = [
                row["user_id"]
                for row in active_before
                if row["user_id"] not in seen_ids
            ]
        if missing_ids:
            placeholders = ",".join("?" * len(missing_ids))
            conn.execute(
                f"""UPDATE guild_members
                    SET status = 'left', left_at = datetime('now'), updated_at = datetime('now')
                    WHERE guild_id = ? AND user_id IN ({placeholders})""",
                [guild_id] + missing_ids,
            )
        conn.commit()
        return {"synced": len(seen_ids), "marked_left": len(missing_ids)}


def mark_guild_member_left(guild_id: str, user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE guild_members
               SET status = 'left', left_at = datetime('now'), updated_at = datetime('now')
               WHERE guild_id = ? AND user_id = ?""",
            (guild_id, user_id),
        )
        conn.commit()


def get_guild_member(guild_id: str, user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM guild_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def _guild_members_where(
    guild_id: str,
    q: str = "",
    status: str = "all",
    role_id: str | None = None,
    presence: str | None = None,
) -> tuple[list[str], list[Any]]:
    clauses = ["guild_id = ?"]
    params: list[Any] = [guild_id]
    if status in {"active", "left"}:
        clauses.append("status = ?")
        params.append(status)
    if q:
        q_like = f"%{q}%"
        clauses.append(
            "(username LIKE ? OR global_name LIKE ? OR display_name LIKE ? OR user_id LIKE ?)"
        )
        params.extend([q_like, q_like, q_like, q_like])
    if role_id:
        clauses.append("(roles_json LIKE ? OR roles_json LIKE ?)")
        params.extend([f'%"id":"{role_id}"%', f'%"id": "{role_id}"%'])
    if presence:
        p = presence.lower()
        if p == "offline":
            clauses.append(
                "(LOWER(COALESCE(presence_status, '')) = 'offline' OR presence_status IS NULL OR presence_status = '')"
            )
        elif p in {"online", "idle", "dnd"}:
            clauses.append("LOWER(COALESCE(presence_status, '')) = ?")
            params.append(p)
    return clauses, params


def list_guild_members(
    guild_id: str,
    q: str = "",
    status: str = "all",
    limit: int = 200,
    offset: int = 0,
    *,
    role_id: str | None = None,
    presence: str | None = None,
) -> list[dict]:
    clauses, params = _guild_members_where(guild_id, q, status, role_id, presence)
    params.append(limit)
    params.append(offset)
    joined_clauses = []
    for clause in clauses:
        if clause == "guild_id = ?":
            joined_clauses.append("gm.guild_id = ?")
        elif clause == "status = ?":
            joined_clauses.append("gm.status = ?")
        elif clause.startswith("(username LIKE"):
            joined_clauses.append(
                "(gm.username LIKE ? OR gm.global_name LIKE ? OR gm.display_name LIKE ? OR gm.user_id LIKE ?)"
            )
        elif clause == "(roles_json LIKE ? OR roles_json LIKE ?)":
            joined_clauses.append("(gm.roles_json LIKE ? OR gm.roles_json LIKE ?)")
        elif clause.startswith("LOWER(COALESCE(presence_status"):
            joined_clauses.append("LOWER(COALESCE(gm.presence_status, '')) = ?")
        elif clause.startswith("(LOWER(COALESCE(presence_status"):
            joined_clauses.append(
                "(LOWER(COALESCE(gm.presence_status, '')) = 'offline' OR gm.presence_status IS NULL OR gm.presence_status = '')"
            )
        else:
            joined_clauses.append(clause)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT gm.*,
                       COUNT(msg.id) AS message_count,
                       MAX(msg.created_at) AS last_message_at
                FROM guild_members gm
                LEFT JOIN guild_messages msg
                  ON msg.guild_id = gm.guild_id
                 AND msg.user_id = gm.user_id
                 AND msg.deleted_at IS NULL
                WHERE {" AND ".join(joined_clauses)}
                GROUP BY gm.id
                ORDER BY gm.status ASC, gm.display_name COLLATE NOCASE ASC
                LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def count_guild_members(
    guild_id: str,
    q: str = "",
    status: str = "all",
    *,
    role_id: str | None = None,
    presence: str | None = None,
) -> int:
    clauses, params = _guild_members_where(guild_id, q, status, role_id, presence)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM guild_members WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return int(row["total"] if row else 0)


def get_guild_member_name_history(guild_id: str, user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT *
               FROM guild_member_name_history
               WHERE guild_id = ? AND user_id = ?
               ORDER BY changed_at DESC""",
            (guild_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]


def _insert_message_history(
    conn: DatabaseConnection,
    *,
    guild_id: str,
    channel_id: str,
    channel_name: str | None,
    message_id: str,
    user_id: str | None,
    event_type: str,
    old_content: str | None,
    new_content: str | None,
    attachment_count: int = 0,
    attachment_urls_json: str | None = None,
    jump_url: str | None = None,
    event_at: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO guild_message_history (
             guild_id, channel_id, channel_name, message_id, user_id, event_type,
             old_content, new_content, attachment_count, attachment_urls_json,
             jump_url, event_at, synced_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), datetime('now'))""",
        (
            guild_id,
            channel_id,
            channel_name,
            message_id,
            user_id,
            event_type,
            old_content,
            new_content,
            int(attachment_count or 0),
            attachment_urls_json,
            jump_url,
            event_at,
        ),
    )


def _attachment_urls_json(message: dict[str, Any]) -> str | None:
    urls = message.get("attachment_urls")
    if isinstance(urls, str):
        return urls
    if isinstance(urls, list):
        return json.dumps([str(url) for url in urls if url], ensure_ascii=False)
    return None


def upsert_guild_message(guild_id: str, message: dict[str, Any]) -> dict:
    channel_id = str(message["channel_id"])
    message_id = str(message["message_id"])
    user_id = str(message["user_id"])
    attachment_urls_json = _attachment_urls_json(message)
    with _connect() as conn:
        existing = conn.execute(
            """SELECT *
               FROM guild_messages
               WHERE guild_id = ? AND channel_id = ? AND message_id = ?""",
            (guild_id, channel_id, message_id),
        ).fetchone()
        new_content = message.get("content")
        old_content = existing.get("content") if existing else None
        old_attachment_urls_json = existing.get("attachment_urls_json") if existing else None
        attachments_changed = (
            existing
            and attachment_urls_json is not None
            and (old_attachment_urls_json or "") != (attachment_urls_json or "")
        )
        if existing and (
            (old_content or "") != (new_content or "") or attachments_changed
        ):
            _insert_message_history(
                conn,
                guild_id=guild_id,
                channel_id=channel_id,
                channel_name=message.get("channel_name")
                or existing.get("channel_name"),
                message_id=message_id,
                user_id=user_id,
                event_type="edit",
                old_content=old_content,
                new_content=new_content,
                attachment_count=int(message.get("attachment_count") or 0),
                attachment_urls_json=attachment_urls_json
                or existing.get("attachment_urls_json"),
                jump_url=message.get("jump_url") or existing.get("jump_url"),
                event_at=message.get("edited_at"),
            )
        conn.execute(
            """INSERT INTO guild_messages (
                 guild_id, channel_id, channel_name, channel_type, parent_channel_id,
                 message_id, user_id, original_content, content,
                 attachment_count, attachment_urls_json, jump_url, created_at,
                 edited_at, deleted_at, synced_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON DUPLICATE KEY UPDATE
                 channel_name = VALUES(channel_name),
                 channel_type = COALESCE(VALUES(channel_type), channel_type),
                 parent_channel_id = COALESCE(VALUES(parent_channel_id), parent_channel_id),
                 user_id = VALUES(user_id),
                 original_content = COALESCE(original_content, VALUES(original_content), content),
                 content = VALUES(content),
                 attachment_count = VALUES(attachment_count),
                 attachment_urls_json = COALESCE(VALUES(attachment_urls_json), attachment_urls_json),
                 jump_url = VALUES(jump_url),
                 created_at = VALUES(created_at),
                 edited_at = VALUES(edited_at),
                 deleted_at = COALESCE(VALUES(deleted_at), deleted_at),
                 synced_at = CURRENT_TIMESTAMP""",
            (
                guild_id,
                channel_id,
                message.get("channel_name"),
                message.get("channel_type"),
                message.get("parent_channel_id"),
                message_id,
                user_id,
                message.get("original_content") or message.get("content"),
                message.get("content"),
                int(message.get("attachment_count") or 0),
                attachment_urls_json,
                message.get("jump_url"),
                message.get("created_at"),
                message.get("edited_at"),
                message.get("deleted_at"),
            ),
        )
        conn.commit()
        row = conn.execute(
            """SELECT * FROM guild_messages
               WHERE guild_id = ? AND channel_id = ? AND message_id = ?""",
            (guild_id, channel_id, message_id),
        ).fetchone()
        return dict(row)


def upsert_guild_messages(
    guild_id: str, messages: list[dict[str, Any]], *, insert_only: bool = False
) -> dict:
    synced = 0
    skipped = 0
    with _connect() as conn:
        for message in messages:
            if (
                not message.get("channel_id")
                or not message.get("message_id")
                or not message.get("user_id")
            ):
                continue
            channel_id = str(message["channel_id"])
            message_id = str(message["message_id"])
            user_id = str(message["user_id"])
            attachment_urls_json = _attachment_urls_json(message)
            existing = conn.execute(
                """SELECT *
                   FROM guild_messages
                   WHERE guild_id = ? AND channel_id = ? AND message_id = ?""",
                (guild_id, channel_id, message_id),
            ).fetchone()
            if insert_only and existing:
                skipped += 1
                continue
            new_content = message.get("content")
            old_content = existing.get("content") if existing else None
            old_attachment_urls_json = (
                existing.get("attachment_urls_json") if existing else None
            )
            attachments_changed = (
                existing
                and attachment_urls_json is not None
                and (old_attachment_urls_json or "") != (attachment_urls_json or "")
            )
            if existing and (
                (old_content or "") != (new_content or "") or attachments_changed
            ):
                _insert_message_history(
                    conn,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    channel_name=message.get("channel_name")
                    or existing.get("channel_name"),
                    message_id=message_id,
                    user_id=user_id,
                    event_type="edit",
                    old_content=old_content,
                    new_content=new_content,
                    attachment_count=int(message.get("attachment_count") or 0),
                    attachment_urls_json=attachment_urls_json
                    or existing.get("attachment_urls_json"),
                    jump_url=message.get("jump_url") or existing.get("jump_url"),
                    event_at=message.get("edited_at"),
                )
            duplicate_update = (
                "message_id = message_id"
                if insert_only
                else """channel_name = VALUES(channel_name),
                     channel_type = COALESCE(VALUES(channel_type), channel_type),
                     parent_channel_id = COALESCE(VALUES(parent_channel_id), parent_channel_id),
                     user_id = VALUES(user_id),
                     original_content = COALESCE(original_content, VALUES(original_content), content),
                     content = VALUES(content),
                     attachment_count = VALUES(attachment_count),
                     attachment_urls_json = COALESCE(VALUES(attachment_urls_json), attachment_urls_json),
                     jump_url = VALUES(jump_url),
                     created_at = VALUES(created_at),
                     edited_at = VALUES(edited_at),
                     deleted_at = COALESCE(VALUES(deleted_at), deleted_at),
                     synced_at = CURRENT_TIMESTAMP"""
            )
            cursor = conn.execute(
                f"""INSERT INTO guild_messages (
                      guild_id, channel_id, channel_name, channel_type, parent_channel_id,
                      message_id, user_id, original_content, content,
                      attachment_count, attachment_urls_json, jump_url, created_at,
                      edited_at, deleted_at, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    ON DUPLICATE KEY UPDATE {duplicate_update}""",
                (
                    guild_id,
                    str(message["channel_id"]),
                    message.get("channel_name"),
                    message.get("channel_type"),
                    message.get("parent_channel_id"),
                    str(message["message_id"]),
                    str(message["user_id"]),
                    message.get("original_content") or message.get("content"),
                    message.get("content"),
                    int(message.get("attachment_count") or 0),
                    attachment_urls_json,
                    message.get("jump_url"),
                    message.get("created_at"),
                    message.get("edited_at"),
                    message.get("deleted_at"),
                ),
            )
            synced += 1 if not insert_only or cursor.rowcount > 0 else 0
        conn.commit()
    return {"synced": synced, "skipped": skipped}


def mark_guild_message_deleted(guild_id: str, channel_id: str, message_id: str) -> None:
    with _connect() as conn:
        existing = conn.execute(
            """SELECT *
               FROM guild_messages
               WHERE guild_id = ? AND channel_id = ? AND message_id = ?""",
            (guild_id, channel_id, message_id),
        ).fetchone()
        if existing and not existing.get("deleted_at"):
            _insert_message_history(
                conn,
                guild_id=guild_id,
                channel_id=channel_id,
                channel_name=existing.get("channel_name"),
                message_id=message_id,
                user_id=existing.get("user_id"),
                event_type="delete",
                old_content=existing.get("content"),
                new_content=None,
                attachment_count=int(existing.get("attachment_count") or 0),
                attachment_urls_json=existing.get("attachment_urls_json"),
                jump_url=existing.get("jump_url"),
            )
        conn.execute(
            """UPDATE guild_messages
               SET deleted_at = datetime('now'), synced_at = datetime('now')
               WHERE guild_id = ? AND channel_id = ? AND message_id = ?""",
            (guild_id, channel_id, message_id),
        )
        conn.commit()


def _channel_filter_clause(
    column: str,
    include_channel_ids: set[str] | None = None,
    exclude_channel_ids: set[str] | None = None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if include_channel_ids is not None:
        ids = sorted(str(channel_id) for channel_id in include_channel_ids if channel_id)
        if not ids:
            clauses.append("1 = 0")
        else:
            clauses.append(f"{column} IN ({','.join('?' for _ in ids)})")
            params.extend(ids)
    if exclude_channel_ids:
        ids = sorted(str(channel_id) for channel_id in exclude_channel_ids if channel_id)
        if ids:
            clauses.append(f"{column} NOT IN ({','.join('?' for _ in ids)})")
            params.extend(ids)
    return clauses, params


def _guild_messages_where(
    guild_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
    q: str = "",
    include_deleted: bool = False,
    include_changed: bool = True,
    exclude_channel_ids: set[str] | None = None,
) -> tuple[list[str], list[Any]]:
    clauses = ["gm.guild_id = ?"]
    params: list[Any] = [guild_id]
    if user_id:
        clauses.append("gm.user_id = ?")
        params.append(user_id)
    if channel_id:
        clauses.append("gm.channel_id = ?")
        params.append(channel_id)
    elif exclude_channel_ids:
        extra_clauses, extra_params = _channel_filter_clause(
            "gm.channel_id", exclude_channel_ids=exclude_channel_ids
        )
        clauses.extend(extra_clauses)
        params.extend(extra_params)
    if q:
        clauses.append(
            "(gm.content LIKE ? OR gm.original_content LIKE ? OR gm.channel_name LIKE ? OR m.display_name LIKE ?)"
        )
        q_like = f"%{q}%"
        params.extend([q_like, q_like, q_like, q_like])
    if not include_deleted:
        clauses.append("gm.deleted_at IS NULL")
    if not include_changed:
        clauses.append("gm.edited_at IS NULL")
    return clauses, params


def list_guild_messages(
    guild_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
    q: str = "",
    include_deleted: bool = False,
    include_changed: bool = True,
    exclude_channel_ids: set[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    clauses, params = _guild_messages_where(
        guild_id, user_id, channel_id, q, include_deleted, include_changed, exclude_channel_ids
    )
    params.extend([limit, offset])
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT gm.*, m.display_name, m.username, m.avatar_url, m.presence_status
                FROM guild_messages gm
                LEFT JOIN guild_members m
                  ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
                WHERE {" AND ".join(clauses)}
                ORDER BY gm.created_at DESC
                LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def count_guild_messages(
    guild_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
    q: str = "",
    include_deleted: bool = False,
    include_changed: bool = True,
    exclude_channel_ids: set[str] | None = None,
) -> int:
    clauses, params = _guild_messages_where(
        guild_id, user_id, channel_id, q, include_deleted, include_changed, exclude_channel_ids
    )
    with _connect() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM guild_messages gm
                LEFT JOIN guild_members m
                  ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
                WHERE {" AND ".join(clauses)}""",
            params,
        ).fetchone()
        return int(row["total"] if row else 0)


def list_guild_message_history(
    guild_id: str,
    user_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    clauses = ["h.guild_id = ?"]
    params: list[Any] = [guild_id]
    if user_id:
        clauses.append("h.user_id = ?")
        params.append(user_id)
    if event_type in {"edit", "delete"}:
        clauses.append("h.event_type = ?")
        params.append(event_type)
    params.extend([limit, offset])
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT h.*, m.display_name, m.username, m.avatar_url
                FROM guild_message_history h
                LEFT JOIN guild_members m
                  ON m.guild_id = h.guild_id AND m.user_id = h.user_id
                WHERE {" AND ".join(clauses)}
                ORDER BY h.event_at DESC
                LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def count_guild_message_history(
    guild_id: str,
    user_id: str | None = None,
    event_type: str | None = None,
) -> int:
    clauses = ["guild_id = ?"]
    params: list[Any] = [guild_id]
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if event_type in {"edit", "delete"}:
        clauses.append("event_type = ?")
        params.append(event_type)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM guild_message_history WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return int(row["total"] if row else 0)


def get_user_message_stats(guild_id: str, user_id: str) -> dict:
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS message_count,
                      COUNT(DISTINCT channel_id) AS channel_count,
                      MAX(created_at) AS last_message_at,
                      SUM(attachment_count) AS attachment_count
               FROM guild_messages
               WHERE guild_id = ? AND user_id = ? AND deleted_at IS NULL""",
            (guild_id, user_id),
        ).fetchone()
        return (
            dict(row)
            if row
            else {
                "message_count": 0,
                "channel_count": 0,
                "last_message_at": None,
                "attachment_count": 0,
            }
        )


def get_user_channel_message_stats(guild_id: str, user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT channel_id, COALESCE(MAX(channel_name), channel_id) AS channel_name,
                      COUNT(*) AS message_count,
                      MAX(created_at) AS last_message_at
               FROM guild_messages
               WHERE guild_id = ? AND user_id = ? AND deleted_at IS NULL
               GROUP BY channel_id
               ORDER BY message_count DESC, channel_name COLLATE NOCASE ASC""",
            (guild_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]


def get_guild_message_overview(
    guild_id: str,
    *,
    include_channel_ids: set[str] | None = None,
    exclude_channel_ids: set[str] | None = None,
) -> dict:
    channel_clauses, channel_params = _channel_filter_clause(
        "channel_id",
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    gm_channel_clauses, gm_channel_params = _channel_filter_clause(
        "gm.channel_id",
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    with _connect() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS message_count,
                      COUNT(DISTINCT user_id) AS active_writers,
                      COUNT(DISTINCT channel_id) AS active_channels,
                      MAX(created_at) AS last_message_at
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL"""
            + (" AND " + " AND ".join(channel_clauses) if channel_clauses else ""),
            [guild_id] + channel_params,
        ).fetchone()
        top_users = conn.execute(
            """SELECT gm.user_id, COUNT(*) AS message_count,
                      MAX(m.display_name) AS display_name,
                      MAX(m.username) AS username,
                      MAX(m.avatar_url) AS avatar_url
               FROM guild_messages gm
               LEFT JOIN guild_members m
                 ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
               WHERE gm.guild_id = ? AND gm.deleted_at IS NULL"""
            + (" AND " + " AND ".join(gm_channel_clauses) if gm_channel_clauses else "")
            + """
               GROUP BY gm.user_id
               ORDER BY message_count DESC
               LIMIT 10""",
            [guild_id] + gm_channel_params,
        ).fetchall()
        top_channels = conn.execute(
            """SELECT channel_id, COALESCE(MAX(channel_name), channel_id) AS channel_name,
                      COUNT(*) AS message_count,
                      MAX(created_at) AS last_message_at
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL"""
            + (" AND " + " AND ".join(channel_clauses) if channel_clauses else "")
            + """
               GROUP BY channel_id
               ORDER BY message_count DESC
               LIMIT 10""",
            [guild_id] + channel_params,
        ).fetchall()
        return {
            "totals": dict(totals) if totals else {},
            "top_users": [dict(r) for r in top_users],
            "top_channels": [dict(r) for r in top_channels],
        }


def get_guild_message_chart_data(
    guild_id: str,
    limit: int = 8,
    *,
    include_channel_ids: set[str] | None = None,
    exclude_channel_ids: set[str] | None = None,
) -> dict:
    channel_clauses, channel_params = _channel_filter_clause(
        "channel_id",
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    gm_channel_clauses, gm_channel_params = _channel_filter_clause(
        "gm.channel_id",
        include_channel_ids=include_channel_ids,
        exclude_channel_ids=exclude_channel_ids,
    )
    with _connect() as conn:
        top_users = conn.execute(
            """SELECT COALESCE(MAX(m.display_name), MAX(m.username), gm.user_id) AS label,
                      COUNT(*) AS value
               FROM guild_messages gm
               LEFT JOIN guild_members m
                 ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
               WHERE gm.guild_id = ? AND gm.deleted_at IS NULL"""
            + (" AND " + " AND ".join(gm_channel_clauses) if gm_channel_clauses else "")
            + """
               GROUP BY gm.user_id
               ORDER BY value DESC
               LIMIT ?""",
            [guild_id] + gm_channel_params + [limit],
        ).fetchall()
        user_total = conn.execute(
            """SELECT COUNT(*) AS total
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL"""
            + (" AND " + " AND ".join(channel_clauses) if channel_clauses else ""),
            [guild_id] + channel_params,
        ).fetchone()
        top_channels = conn.execute(
            """SELECT COALESCE(MAX(channel_name), channel_id) AS label,
                      COUNT(*) AS value
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL"""
            + (" AND " + " AND ".join(channel_clauses) if channel_clauses else "")
            + """
               GROUP BY channel_id
               ORDER BY value DESC
               LIMIT ?""",
            [guild_id] + channel_params + [limit],
        ).fetchall()
        status_rows = (
            conn.execute(
                """SELECT
                 SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) AS deleted_count,
                 SUM(CASE WHEN deleted_at IS NULL AND edited_at IS NOT NULL AND COALESCE(original_content, '') <> COALESCE(content, '') THEN 1 ELSE 0 END) AS edited_count,
                 SUM(CASE WHEN deleted_at IS NULL AND NOT (edited_at IS NOT NULL AND COALESCE(original_content, '') <> COALESCE(content, '')) THEN 1 ELSE 0 END) AS original_count
               FROM guild_messages
               WHERE guild_id = ?"""
                + (
                    " AND " + " AND ".join(channel_clauses)
                    if channel_clauses
                    else ""
                ),
                [guild_id] + channel_params,
            ).fetchone()
            or {}
        )

    def with_other(rows: list[dict], total: int) -> list[dict]:
        items = [
            {"label": str(row["label"] or "-"), "value": int(row["value"] or 0)}
            for row in rows
        ]
        shown = sum(item["value"] for item in items)
        other = max(0, int(total or 0) - shown)
        if other:
            items.append({"label": "Weitere", "value": other})
        return items

    total = int((user_total or {}).get("total") or 0)
    return {
        "users": with_other([dict(r) for r in top_users], total),
        "channels": with_other([dict(r) for r in top_channels], total),
        "overall": [
            {"label": "Original", "value": int(status_rows.get("original_count") or 0)},
            {"label": "Bearbeitet", "value": int(status_rows.get("edited_count") or 0)},
            {"label": "Gelöscht", "value": int(status_rows.get("deleted_count") or 0)},
        ],
    }


def list_message_filter_users(
    guild_id: str,
    limit: int = 500,
    *,
    exclude_channel_ids: set[str] | None = None,
) -> list[dict]:
    channel_clauses, channel_params = _channel_filter_clause(
        "gm.channel_id", exclude_channel_ids=exclude_channel_ids
    )
    with _connect() as conn:
        rows = conn.execute(
            """SELECT gm.user_id,
                      COUNT(*) AS message_count,
                      MAX(m.display_name) AS display_name,
                      MAX(m.username) AS username,
                      MAX(u.discord_username) AS oauth_username
               FROM guild_messages gm
               LEFT JOIN guild_members m
                 ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
               LEFT JOIN users u
                 ON u.discord_id = gm.user_id
               WHERE gm.guild_id = ? AND gm.deleted_at IS NULL"""
            + (" AND " + " AND ".join(channel_clauses) if channel_clauses else "")
            + """
               GROUP BY gm.user_id
               ORDER BY COALESCE(MAX(m.display_name), MAX(m.username), MAX(u.discord_username), gm.user_id) COLLATE NOCASE ASC
               LIMIT ?""",
            [guild_id] + channel_params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


def list_message_filter_channels(
    guild_id: str,
    limit: int = 500,
    *,
    exclude_channel_ids: set[str] | None = None,
) -> list[dict]:
    channel_clauses, channel_params = _channel_filter_clause(
        "channel_id", exclude_channel_ids=exclude_channel_ids
    )
    with _connect() as conn:
        rows = conn.execute(
            """SELECT channel_id,
                      COALESCE(MAX(channel_name), channel_id) AS channel_name,
                      COUNT(*) AS message_count
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL"""
            + (" AND " + " AND ".join(channel_clauses) if channel_clauses else "")
            + """
               GROUP BY channel_id
               ORDER BY channel_name COLLATE NOCASE ASC
               LIMIT ?""",
            [guild_id] + channel_params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


# ══════════ Roles & Permissions ══════════

ALL_PERMISSIONS = [
    "admin",
    "team_updates.view",
    "team_updates.send",
    "bot_updates.view",
    "bot_updates.send",
    "tickets.view",
    "tickets.reply",
    "tickets.close",
    "tickets.discord.view",
    "tickets.twitch.view",
    "tickets.general.view",
    "tickets.admin.view",
    "users.view",
    "users.warn",
    "users.ban",
    "users.timeout",
    "counting.view",
    "counting.manage",
    "birthdays.view",
    "birthdays.manage",
    "stats.view",
    "stats.manage",
    "warnings.view",
    "warnings.manage",
    "minecraft.view",
    "minecraft.players.view",
    "minecraft.moderation.view",
    "roles.manage",
    "config.manage",
    "logs.view",
    "logs.manage",
    "commands.all.use",
    "commands.ticket.panel.use",
    "commands.ticket.close.use",
    "commands.ticket.useradd.use",
    "commands.ticket.userremove.use",
    "commands.admin.ticket.use",
    "commands.counting.set.use",
    "commands.counting.reset.use",
    "commands.counting.info.use",
    "commands.counting.leaderboard.use",
    "commands.logs.use",
    "commands.messagesync.use",
]


PERMISSION_GROUPS = [
    {
        "key": "team_updates",
        "label": "Änderungen",
        "permissions": [
            ("team_updates.view", "Team Änderungen ansehen"),
            ("team_updates.send", "Team Änderungen senden"),
            ("bot_updates.view", "Bot Änderungen ansehen"),
            ("bot_updates.send", "Bot Änderungen senden"),
        ],
    },
    {
        "key": "tickets",
        "label": "Tickets",
        "permissions": [
            ("tickets.view", "Alle Tickets ansehen"),
            ("tickets.discord.view", "Discord Tickets ansehen"),
            ("tickets.twitch.view", "Twitch Tickets ansehen"),
            ("tickets.general.view", "Allgemeine Tickets ansehen"),
            ("tickets.admin.view", "Admin Tickets ansehen"),
            ("tickets.reply", "Antworten"),
            ("tickets.close", "Schliessen"),
        ],
    },
    {
        "key": "users",
        "label": "Users",
        "permissions": [
            ("users.view", "Ansehen"),
            ("users.warn", "Verwarnen"),
            ("users.ban", "Bannen"),
            ("users.timeout", "Timeout"),
        ],
    },
    {
        "key": "counting",
        "label": "Counting",
        "permissions": [
            ("counting.view", "Ansehen"),
            ("counting.manage", "Verwalten"),
        ],
    },
    {
        "key": "features",
        "label": "Features",
        "permissions": [
            ("birthdays.view", "Geburtstage ansehen"),
            ("birthdays.manage", "Geburtstage verwalten"),
            ("stats.view", "Statistiken ansehen"),
            ("stats.manage", "Statistiken verwalten"),
            ("warnings.view", "Verwarnungen ansehen"),
            ("warnings.manage", "Verwarnungen verwalten"),
        ],
    },
    {
        "key": "minecraft",
        "label": "Minecraft",
        "permissions": [
            ("minecraft.view", "Voller Lesezugriff"),
            ("minecraft.players.view", "Nur Spieler & Statistiken"),
            ("minecraft.moderation.view", "Nur Strafen & Reports"),
        ],
    },
    {
        "key": "system",
        "label": "System",
        "permissions": [
            ("roles.manage", "Web Rollen verwalten"),
            ("config.manage", "Konfiguration verwalten"),
            ("logs.view", "Logs ansehen"),
            ("logs.manage", "Logs verwalten"),
        ],
    },
]

COMMAND_PERMISSION_GROUPS = [
    {
        "key": "commands",
        "label": "Commands",
        "permissions": [
            ("commands.all.use", "Alle Commands"),
            ("commands.ticket.panel.use", "/ticket panel"),
            ("commands.ticket.close.use", "/ticket close"),
            ("commands.ticket.useradd.use", "/ticket useradd"),
            ("commands.ticket.userremove.use", "/ticket userremove"),
            ("commands.admin.ticket.use", "/admin ticket"),
            ("commands.counting.set.use", "/counting set"),
            ("commands.counting.reset.use", "/counting reset"),
            ("commands.counting.info.use", "/counting info"),
            ("commands.counting.leaderboard.use", "/counting leaderboard"),
            ("commands.logs.use", "/logs"),
            ("commands.messagesync.use", "/message-sync"),
        ],
    },
]


def list_roles(guild_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM roles WHERE guild_id = ? ORDER BY role_name", (guild_id,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["permissions"] = json.loads(d.get("permissions") or "[]")
            result.append(d)
        return result


def parse_member_roles(member: dict | None) -> list[dict]:
    if not member:
        return []
    try:
        roles = json.loads(member.get("roles_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [
        role
        for role in roles
        if isinstance(role, dict) and (role.get("id") or role.get("name"))
    ]


def update_guild_member_roles(
    guild_id: str, user_id: str, roles: list[dict[str, Any]]
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE guild_members
               SET roles_json = ?, updated_at = datetime('now')
               WHERE guild_id = ? AND user_id = ?""",
            (json.dumps(roles or [], ensure_ascii=False), guild_id, user_id),
        )
        conn.commit()


def update_guild_member_profile_fields(
    guild_id: str,
    user_id: str,
    *,
    banner_url: str | None = None,
    accent_color: int | None = None,
    locale: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE guild_members
               SET banner_url = COALESCE(?, banner_url),
                   accent_color = COALESCE(?, accent_color),
                   locale = COALESCE(?, locale),
                   updated_at = datetime('now')
               WHERE guild_id = ? AND user_id = ?""",
            (banner_url, accent_color, locale, guild_id, user_id),
        )
        conn.commit()


def get_role(role_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["permissions"] = json.loads(d.get("permissions") or "[]")
        return d


def create_role(
    guild_id: str, discord_role_id: str, role_name: str, permissions: list[str]
) -> dict:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO roles (guild_id, discord_role_id, role_name, permissions) VALUES (?, ?, ?, ?)",
            (guild_id, discord_role_id, role_name, json.dumps(permissions)),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM roles WHERE guild_id = ? AND discord_role_id = ?",
            (guild_id, discord_role_id),
        ).fetchone()
        d = dict(row)
        d["permissions"] = json.loads(d.get("permissions") or "[]")
        return d


def update_role(
    role_id: int, role_name: str | None = None, permissions: list[str] | None = None
) -> None:
    parts, params = [], []
    if role_name is not None:
        parts.append("role_name = ?")
        params.append(role_name)
    if permissions is not None:
        parts.append("permissions = ?")
        params.append(json.dumps(permissions))
    if not parts:
        return
    params.append(role_id)
    with _connect() as conn:
        conn.execute(f"UPDATE roles SET {', '.join(parts)} WHERE id = ?", params)
        conn.commit()


def delete_role(role_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
        conn.commit()


PERMISSION_LABELS: dict[str, str] = {
    perm: label
    for group in (PERMISSION_GROUPS + COMMAND_PERMISSION_GROUPS)
    for perm, label in group["permissions"]
}
PERMISSION_LABELS["admin"] = "Vollzugriff"


def permission_label(perm: str) -> str:
    return PERMISSION_LABELS.get(perm, perm)


def _role_member_like_patterns(discord_role_id: str) -> tuple[str, str]:
    return (
        f'%"id": "{discord_role_id}"%',
        f'%"id":"{discord_role_id}"%',
    )


def list_role_members(
    guild_id: str, discord_role_id: str, limit: int = 500
) -> list[dict]:
    if not discord_role_id:
        return []
    pat, pat_compact = _role_member_like_patterns(discord_role_id)
    with _connect() as conn:
        rows = conn.execute(
            """SELECT user_id, username, display_name, global_name, avatar_url,
                      status, presence_status, joined_at
               FROM guild_members
               WHERE guild_id = ?
                 AND (roles_json LIKE ? OR roles_json LIKE ?)
               ORDER BY status ASC, COALESCE(display_name, username, user_id) COLLATE NOCASE ASC
               LIMIT ?""",
            (guild_id, pat, pat_compact, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def count_role_members(guild_id: str, discord_role_id: str) -> int:
    if not discord_role_id:
        return 0
    pat, pat_compact = _role_member_like_patterns(discord_role_id)
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total
               FROM guild_members
               WHERE guild_id = ?
                 AND (roles_json LIKE ? OR roles_json LIKE ?)""",
            (guild_id, pat, pat_compact),
        ).fetchone()
        return int(row["total"]) if row else 0


def get_permissions_for_discord_roles(
    guild_id: str, discord_role_ids: list[str]
) -> set[str]:
    if not discord_role_ids:
        return set()
    placeholders = ",".join("?" * len(discord_role_ids))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT permissions FROM roles WHERE guild_id = ? AND discord_role_id IN ({placeholders})",
            [guild_id] + discord_role_ids,
        ).fetchall()
    perms: set[str] = set()
    for row in rows:
        p = json.loads(row["permissions"] or "[]")
        perms.update(p)
    if "admin" in perms:
        perms = set(ALL_PERMISSIONS)
    return perms


# ══════════ Guild Config ══════════


def get_config(guild_id: str, key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT config_value FROM guild_config WHERE guild_id = ? AND config_key = ?",
            (guild_id, key),
        ).fetchone()
        return row["config_value"] if row else None


def set_config(guild_id: str, key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO guild_config (guild_id, config_key, config_value)
               VALUES (?, ?, ?)
               ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)""",
            (guild_id, key, value),
        )
        conn.commit()


def delete_config(guild_id: str, key: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM guild_config WHERE guild_id = ? AND config_key = ?",
            (guild_id, key),
        )
        conn.commit()


# ══════════ Birthdays ══════════


def get_birthdays(
    guild_id: str, limit: int | None = None, offset: int = 0
) -> list[dict]:
    with _connect() as conn:
        if limit is None:
            rows = conn.execute(
                "SELECT * FROM birthdays WHERE guild_id = ? ORDER BY month, day",
                (guild_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM birthdays
                   WHERE guild_id = ?
                   ORDER BY month, day
                   LIMIT ? OFFSET ?""",
                (guild_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def count_birthdays(guild_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM birthdays WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return int(row["total"] if row else 0)


def get_birthday(guild_id: str, user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM birthdays WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def set_birthday(
    guild_id: str, user_id: str, day: int, month: int, year: int | None = None
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO birthdays (guild_id, user_id, day, month, year)
               VALUES (?, ?, ?, ?, ?)
               ON DUPLICATE KEY UPDATE
                 day = VALUES(day), month = VALUES(month), year = VALUES(year)""",
            (guild_id, user_id, day, month, year),
        )
        conn.commit()


def delete_birthday(guild_id: str, user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        conn.commit()


def get_birthdays_today(guild_id: str) -> list[dict]:
    now = berlin_today()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM birthdays WHERE guild_id = ? AND month = ? AND day = ?",
            (guild_id, now.month, now.day),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_birthday_congrats(guild_id: str, user_id: str) -> None:
    now_iso = berlin_today().isoformat()
    with _connect() as conn:
        conn.execute(
            "UPDATE birthdays SET last_congrats = ? WHERE guild_id = ? AND user_id = ?",
            (now_iso, guild_id, user_id),
        )
        conn.commit()


def count_birthdays_in_month(guild_id: str, month: int) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM birthdays WHERE guild_id = ? AND month = ?",
            (guild_id, int(month)),
        ).fetchone()
        return int(row["total"] if row else 0)


def get_upcoming_birthdays(
    guild_id: str, days: int = 30, limit: int = 10
) -> list[dict]:
    """Return birthdays within the next `days` days (wraps year), ordered chronologically."""
    today = berlin_today()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, day, month, year FROM birthdays WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    entries: list[tuple[int, dict]] = []
    for r in rows:
        d = dict(r)
        try:
            this_year = today.replace(month=int(d["month"]), day=int(d["day"]))
        except ValueError:
            continue
        delta = (this_year - today).days
        if delta < 0:
            try:
                next_year = today.replace(
                    year=today.year + 1, month=int(d["month"]), day=int(d["day"])
                )
                delta = (next_year - today).days
            except ValueError:
                continue
        if delta <= days:
            d["days_until"] = delta
            entries.append((delta, d))
    entries.sort(key=lambda x: x[0])
    return [e[1] for e in entries[:limit]]


def list_bot_messages(guild_id: str, message_type: str | None = None) -> list[dict]:
    with _connect() as conn:
        if message_type is None:
            rows = conn.execute(
                "SELECT * FROM bot_messages WHERE guild_id = ? ORDER BY created_at ASC",
                (guild_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM bot_messages
                   WHERE guild_id = ? AND message_type = ?
                   ORDER BY created_at ASC""",
                (guild_id, message_type),
            ).fetchall()
        return [dict(r) for r in rows]


def upsert_bot_message(
    guild_id: str,
    message_type: str,
    message_id: str,
    channel_id: str | None = None,
    meta_key: str | None = None,
) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO bot_messages (guild_id, message_type, message_id, channel_id, meta_key)
               VALUES (?, ?, ?, ?, ?)
               ON DUPLICATE KEY UPDATE
                 channel_id = VALUES(channel_id),
                 meta_key = COALESCE(VALUES(meta_key), meta_key),
                 updated_at = CURRENT_TIMESTAMP""",
            (guild_id, message_type, message_id, channel_id, meta_key),
        )
        conn.commit()
        row = conn.execute(
            """SELECT * FROM bot_messages
               WHERE guild_id = ? AND message_type = ? AND message_id = ?""",
            (guild_id, message_type, message_id),
        ).fetchone()
        return dict(row)


def delete_bot_message(guild_id: str, message_type: str, message_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM bot_messages WHERE guild_id = ? AND message_type = ? AND message_id = ?",
            (guild_id, message_type, message_id),
        )
        conn.commit()


# ══════════ Warnings ══════════


def get_warnings(
    guild_id: str, user_id: str, limit: int | None = None, offset: int = 0
) -> list[dict]:
    with _connect() as conn:
        if limit is None:
            rows = conn.execute(
                "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
                (guild_id, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM warnings
                   WHERE guild_id = ? AND user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (guild_id, user_id, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def add_warning(guild_id: str, user_id: str, moderator_id: str, reason: str) -> dict:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason),
        )
        warning_id = conn.conn.insert_id()
        conn.commit()
        row = conn.execute(
            "SELECT * FROM warnings WHERE id = ?", (warning_id,)
        ).fetchone()
        return dict(row)


def remove_warning(warning_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM warnings WHERE id = ?", (warning_id,))
        conn.commit()


def clear_warnings(guild_id: str, user_id: str) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        conn.commit()
        return cursor.rowcount


def _warnings_filter_clauses(
    guild_id: str,
    user_id: str | None = None,
    moderator_id: str | None = None,
    reason_query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["guild_id = ?"]
    params: list[Any] = [guild_id]
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if moderator_id:
        clauses.append("moderator_id = ?")
        params.append(moderator_id)
    if reason_query:
        clauses.append("LOWER(COALESCE(reason, '')) LIKE ?")
        params.append(f"%{reason_query.lower()}%")
    if date_from:
        clauses.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("created_at <= ?")
        params.append(date_to)
    return " AND ".join(clauses), params


def list_all_warnings(
    guild_id: str,
    limit: int = 200,
    offset: int = 0,
    *,
    user_id: str | None = None,
    moderator_id: str | None = None,
    reason_query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    where, params = _warnings_filter_clauses(
        guild_id, user_id, moderator_id, reason_query, date_from, date_to
    )
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM warnings
               WHERE {where}
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_warnings(
    guild_id: str,
    user_id: str | None = None,
    *,
    moderator_id: str | None = None,
    reason_query: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> int:
    where, params = _warnings_filter_clauses(
        guild_id, user_id, moderator_id, reason_query, date_from, date_to
    )
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM warnings WHERE {where}",
            tuple(params),
        ).fetchone()
        return int(row["total"] if row else 0)


# ══════════ Counting ══════════


def get_counting(guild_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM counting_state WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return dict(row) if row else None


def set_counting(guild_id: str, **kwargs: Any) -> None:
    existing = get_counting(guild_id)
    if existing is None:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO counting_state (guild_id, channel_id, last_number, last_user_id, highscore)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    kwargs.get("channel_id"),
                    kwargs.get("last_number", 0),
                    kwargs.get("last_user_id"),
                    kwargs.get("highscore", 0),
                ),
            )
            conn.commit()
    else:
        parts, params = [], []
        for key in ("channel_id", "last_number", "last_user_id", "highscore"):
            if key in kwargs:
                parts.append(f"{key} = ?")
                params.append(kwargs[key])
        if parts:
            params.append(guild_id)
            with _connect() as conn:
                conn.execute(
                    f"UPDATE counting_state SET {', '.join(parts)} WHERE guild_id = ?",
                    params,
                )
                conn.commit()


def get_counting_stats(guild_id: str, user_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM counting_user_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def set_counting_stats(guild_id: str, user_id: str, **kwargs: Any) -> None:
    existing = get_counting_stats(guild_id, user_id)
    if existing is None:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO counting_user_stats
                   (guild_id, user_id, correct, fails, best_streak, current_streak)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    user_id,
                    kwargs.get("correct", 0),
                    kwargs.get("fails", 0),
                    kwargs.get("best_streak", 0),
                    kwargs.get("current_streak", 0),
                ),
            )
            conn.commit()
    else:
        parts, params = [], []
        for key in ("correct", "fails", "best_streak", "current_streak"):
            if key in kwargs:
                parts.append(f"{key} = ?")
                params.append(kwargs[key])
        if parts:
            params.extend([guild_id, user_id])
            with _connect() as conn:
                conn.execute(
                    f"UPDATE counting_user_stats SET {', '.join(parts)} WHERE guild_id = ? AND user_id = ?",
                    params,
                )
                conn.commit()


def get_counting_leaderboard(
    guild_id: str, limit: int = 10, offset: int = 0
) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT s.*, m.display_name, m.username, m.status AS member_status
               FROM counting_user_stats s
               LEFT JOIN guild_members m
                 ON m.guild_id = s.guild_id AND m.user_id = s.user_id
               WHERE s.guild_id = ?
               ORDER BY s.correct DESC
               LIMIT ? OFFSET ?""",
            (guild_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_counting_leaderboard(guild_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM counting_user_stats WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return int(row["total"] if row else 0)


# ══════════ Auto Publisher ══════════


def get_auto_publisher_channels(guild_id: str) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT channel_id FROM auto_publisher_channels WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return [row["channel_id"] for row in rows]


def add_auto_publisher_channel(guild_id: str, channel_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT IGNORE INTO auto_publisher_channels (guild_id, channel_id) VALUES (?, ?)",
            (guild_id, channel_id),
        )
        conn.commit()


def remove_auto_publisher_channel(guild_id: str, channel_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM auto_publisher_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        conn.commit()


# ══════════ Selfroles ══════════


def get_selfrole_panel(message_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM selfrole_panels WHERE message_id = ?", (message_id,)
        ).fetchone()
        if not row:
            return None
        panel = dict(row)
        mappings = conn.execute(
            "SELECT emoji, role_id FROM selfrole_mappings WHERE panel_id = ? ORDER BY id ASC",
            (panel["id"],),
        ).fetchall()
        panel["roles"] = {m["emoji"]: m["role_id"] for m in mappings}
        return panel


def get_selfrole_role_ids(guild_id: str) -> set[str]:
    """Return the set of Discord role IDs used in any selfrole panel mapping."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT m.role_id
                 FROM selfrole_mappings m
                 JOIN selfrole_panels p ON p.id = m.panel_id
                WHERE p.guild_id = ?""",
            (guild_id,),
        ).fetchall()
        return {str(r["role_id"]) for r in rows if r.get("role_id")}


def get_all_selfrole_panels(guild_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM selfrole_panels WHERE guild_id = ? ORDER BY title COLLATE NOCASE ASC, id ASC",
            (guild_id,),
        ).fetchall()
        panels = []
        for row in rows:
            panel = dict(row)
            mappings = conn.execute(
                "SELECT emoji, role_id FROM selfrole_mappings WHERE panel_id = ? ORDER BY id ASC",
                (panel["id"],),
            ).fetchall()
            panel["roles"] = {m["emoji"]: m["role_id"] for m in mappings}
            panels.append(panel)
        return panels


def create_selfrole_panel(
    guild_id: str,
    message_id: str,
    channel_id: str,
    title: str,
    max_roles: int,
    roles: dict[str, str],
) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO selfrole_panels (guild_id, message_id, channel_id, title, max_roles)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, message_id, channel_id, title, max_roles),
        )
        panel_id = conn.conn.insert_id()
        for emoji, role_id in roles.items():
            conn.execute(
                "INSERT INTO selfrole_mappings (panel_id, emoji, role_id) VALUES (?, ?, ?)",
                (panel_id, emoji, role_id),
            )
        conn.commit()
    return get_selfrole_panel(message_id)


def add_selfrole_mapping(message_id: str, emoji: str, role_id: str) -> None:
    panel = get_selfrole_panel(message_id)
    if not panel:
        return
    with _connect() as conn:
        conn.execute(
            """INSERT INTO selfrole_mappings (panel_id, emoji, role_id)
               VALUES (?, ?, ?)
               ON DUPLICATE KEY UPDATE role_id = VALUES(role_id)""",
            (panel["id"], emoji, role_id),
        )
        conn.commit()


def remove_selfrole_mapping(message_id: str, emoji: str) -> None:
    panel = get_selfrole_panel(message_id)
    if not panel:
        return
    with _connect() as conn:
        conn.execute(
            "DELETE FROM selfrole_mappings WHERE panel_id = ? AND emoji = ?",
            (panel["id"], emoji),
        )
        conn.commit()


def delete_selfrole_panel(message_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM selfrole_panels WHERE message_id = ?", (message_id,))
        conn.commit()


# ══════════ Server Stats ══════════


def get_server_stats(guild_id: str) -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT stat_key, channel_id, category_id FROM server_stats WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        result: dict[str, Any] = {"category_id": None}
        for row in rows:
            result[row["stat_key"]] = row["channel_id"]
            if row["category_id"]:
                result["category_id"] = row["category_id"]
        return result


def set_server_stats(
    guild_id: str, category_id: str | None, stats: dict[str, str]
) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM server_stats WHERE guild_id = ?", (guild_id,))
        for key, channel_id in stats.items():
            if key == "category_id":
                continue
            conn.execute(
                "INSERT INTO server_stats (guild_id, category_id, stat_key, channel_id) VALUES (?, ?, ?, ?)",
                (guild_id, category_id, key, channel_id),
            )
        conn.commit()


# ══════════ Channel Name Lookup ══════════


def get_channel_names(guild_id: str, channel_ids) -> dict[str, str]:
    """Best-effort lookup of channel display names from cached message/log data."""
    if not channel_ids:
        return {}
    ids = [str(c) for c in channel_ids if c]
    if not ids:
        return {}
    placeholders = ",".join(["?"] * len(ids))
    result: dict[str, str] = {}
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT channel_id, MAX(channel_name) AS channel_name
                FROM guild_messages
                WHERE guild_id = ? AND channel_id IN ({placeholders})
                  AND channel_name IS NOT NULL AND channel_name <> ''
                GROUP BY channel_id""",
            (guild_id, *ids),
        ).fetchall()
        for row in rows:
            if row.get("channel_name"):
                result[str(row["channel_id"])] = row["channel_name"]
        missing = [i for i in ids if i not in result]
        if missing:
            ph2 = ",".join(["?"] * len(missing))
            rows = conn.execute(
                f"""SELECT channel_id, MAX(channel_name) AS channel_name
                    FROM discord_log_entries
                    WHERE guild_id = ? AND channel_id IN ({ph2})
                      AND channel_name IS NOT NULL AND channel_name <> ''
                    GROUP BY channel_id""",
                (guild_id, *missing),
            ).fetchall()
            for row in rows:
                if row.get("channel_name"):
                    result[str(row["channel_id"])] = row["channel_name"]
    return result


def get_channel_name(guild_id: str, channel_id: str) -> str | None:
    names = get_channel_names(guild_id, [channel_id])
    return names.get(str(channel_id))


# ══════════ Log Channels ══════════


def get_log_channel(guild_id: str, log_type: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT channel_id FROM log_channels WHERE guild_id = ? AND log_type = ?",
            (guild_id, log_type),
        ).fetchone()
        return row["channel_id"] if row else None


def set_log_channel(guild_id: str, log_type: str, channel_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO log_channels (guild_id, log_type, channel_id)
               VALUES (?, ?, ?)
               ON DUPLICATE KEY UPDATE channel_id = VALUES(channel_id)""",
            (guild_id, log_type, channel_id),
        )
        conn.commit()


def remove_log_channel(guild_id: str, log_type: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM log_channels WHERE guild_id = ? AND log_type = ?",
            (guild_id, log_type),
        )
        conn.commit()


def get_all_log_channels(guild_id: str) -> dict[str, str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT log_type, channel_id FROM log_channels WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
        return {row["log_type"]: row["channel_id"] for row in rows}


# ══════════ Discord Log Entries ══════════


def _discord_log_where(
    guild_id: str,
    log_type: str | None = None,
    channel_id: str | None = None,
    q: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["guild_id = ?"]
    params: list[Any] = [guild_id]
    if log_type:
        clauses.append("log_type = ?")
        params.append(log_type)
    if channel_id:
        clauses.append("channel_id = ?")
        params.append(str(channel_id))
    if q:
        pattern = f"%{q}%"
        clauses.append(
            "(content LIKE ? OR event_title LIKE ? OR event_summary LIKE ? OR actor_name LIKE ? OR actor_id LIKE ? OR author_name LIKE ? OR author_id LIKE ? OR channel_name LIKE ?)"
        )
        params.extend([pattern, pattern, pattern, pattern, pattern, pattern, pattern, pattern])
    return " AND ".join(clauses), params


def upsert_discord_log_entry(
    guild_id: str, log_type: str, entry: dict[str, Any]
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO discord_log_entries
               (guild_id, log_type, channel_id, channel_name, message_id, author_id,
                author_name, actor_id, actor_name, event_title, event_summary, content,
                embed_count, attachment_count, jump_url, created_at, edited_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON DUPLICATE KEY UPDATE
                 log_type = VALUES(log_type),
                 channel_name = VALUES(channel_name),
                 author_id = VALUES(author_id),
                 author_name = VALUES(author_name),
                 actor_id = COALESCE(VALUES(actor_id), actor_id),
                 actor_name = COALESCE(VALUES(actor_name), actor_name),
                 event_title = VALUES(event_title),
                 event_summary = VALUES(event_summary),
                 content = VALUES(content),
                 embed_count = VALUES(embed_count),
                 attachment_count = VALUES(attachment_count),
                 jump_url = VALUES(jump_url),
                 created_at = VALUES(created_at),
                 edited_at = VALUES(edited_at)""",
            (
                guild_id,
                log_type,
                entry.get("channel_id"),
                entry.get("channel_name"),
                entry.get("message_id"),
                entry.get("author_id"),
                entry.get("author_name"),
                entry.get("actor_id"),
                entry.get("actor_name"),
                entry.get("event_title"),
                entry.get("event_summary"),
                entry.get("content") or "",
                int(entry.get("embed_count") or 0),
                int(entry.get("attachment_count") or 0),
                entry.get("jump_url"),
                entry.get("created_at"),
                entry.get("edited_at"),
            ),
        )
        conn.commit()


def upsert_discord_log_entries(
    guild_id: str,
    log_type: str,
    entries: list[dict[str, Any]],
) -> int:
    if not entries:
        return 0
    with _connect() as conn:
        for entry in entries:
            conn.execute(
                """INSERT INTO discord_log_entries
                   (guild_id, log_type, channel_id, channel_name, message_id, author_id,
                    author_name, actor_id, actor_name, event_title, event_summary,
                    content, embed_count, attachment_count, jump_url, created_at, edited_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON DUPLICATE KEY UPDATE
                     log_type = VALUES(log_type),
                     channel_name = VALUES(channel_name),
                     author_id = VALUES(author_id),
                     author_name = VALUES(author_name),
                     actor_id = COALESCE(VALUES(actor_id), actor_id),
                     actor_name = COALESCE(VALUES(actor_name), actor_name),
                     event_title = VALUES(event_title),
                     event_summary = VALUES(event_summary),
                     content = VALUES(content),
                     embed_count = VALUES(embed_count),
                     attachment_count = VALUES(attachment_count),
                     jump_url = VALUES(jump_url),
                     created_at = VALUES(created_at),
                     edited_at = VALUES(edited_at)""",
                (
                    guild_id,
                    log_type,
                    entry.get("channel_id"),
                    entry.get("channel_name"),
                    entry.get("message_id"),
                    entry.get("author_id"),
                    entry.get("author_name"),
                    entry.get("actor_id"),
                    entry.get("actor_name"),
                    entry.get("event_title"),
                    entry.get("event_summary"),
                    entry.get("content") or "",
                    int(entry.get("embed_count") or 0),
                    int(entry.get("attachment_count") or 0),
                    entry.get("jump_url"),
                    entry.get("created_at"),
                    entry.get("edited_at"),
                ),
            )
        conn.commit()
        return len(entries)


def list_discord_log_entries(
    guild_id: str,
    log_type: str | None = None,
    channel_id: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    where_sql, params = _discord_log_where(guild_id, log_type, channel_id, q)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT *
                FROM discord_log_entries
                WHERE {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]


def count_discord_log_entries(
    guild_id: str,
    log_type: str | None = None,
    channel_id: str | None = None,
    q: str | None = None,
) -> int:
    where_sql, params = _discord_log_where(guild_id, log_type, channel_id, q)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM discord_log_entries WHERE {where_sql}",
            params,
        ).fetchone()
        return int(row["total"] if row else 0)


def get_discord_log_overview(guild_id: str) -> dict:
    with _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS total FROM discord_log_entries WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        latest = conn.execute(
            """SELECT MAX(created_at) AS latest_created_at, MAX(synced_at) AS latest_synced_at
               FROM discord_log_entries
               WHERE guild_id = ?""",
            (guild_id,),
        ).fetchone()
        by_type_rows = conn.execute(
            """SELECT log_type, COUNT(*) AS total
               FROM discord_log_entries
               WHERE guild_id = ?
               GROUP BY log_type
               ORDER BY log_type""",
            (guild_id,),
        ).fetchall()
        return {
            "total": int(total["total"] if total else 0),
            "latest_created_at": latest["latest_created_at"] if latest else None,
            "latest_synced_at": latest["latest_synced_at"] if latest else None,
            "by_type": [dict(row) for row in by_type_rows],
        }


# ══════════ Twitch Config ══════════


def get_twitch_config(guild_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM twitch_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return dict(row) if row else None


def set_twitch_config(
    guild_id: str, channel_id: str | None = None, last_stream_id: str | None = None
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO twitch_config (guild_id, channel_id, last_stream_id)
               VALUES (?, ?, ?)
               ON DUPLICATE KEY UPDATE
                 channel_id = COALESCE(VALUES(channel_id), channel_id),
                 last_stream_id = COALESCE(VALUES(last_stream_id), last_stream_id)""",
            (guild_id, channel_id, last_stream_id),
        )
        conn.commit()


def remove_twitch_config(guild_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM twitch_config WHERE guild_id = ?", (guild_id,))
        conn.commit()


# ══════════ Tickets (enhanced) ══════════


def upsert_ticket(ticket: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO tickets (
                 ticket_id, guild_id, channel_id, creator_user_id, creator_username,
                 status, subject, category, twitch_name, closed_at, closed_by_id, closed_by_name,
                 close_reason, transcript_path, transcript_url, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
               ON DUPLICATE KEY UPDATE
                 guild_id = COALESCE(VALUES(guild_id), guild_id),
                 channel_id = COALESCE(VALUES(channel_id), channel_id),
                 creator_user_id = COALESCE(VALUES(creator_user_id), creator_user_id),
                 creator_username = COALESCE(VALUES(creator_username), creator_username),
                 status = COALESCE(VALUES(status), status),
                 subject = COALESCE(VALUES(subject), subject),
                 category = COALESCE(VALUES(category), category),
                 twitch_name = COALESCE(VALUES(twitch_name), twitch_name),
                 closed_at = COALESCE(VALUES(closed_at), closed_at),
                 closed_by_id = COALESCE(VALUES(closed_by_id), closed_by_id),
                 closed_by_name = COALESCE(VALUES(closed_by_name), closed_by_name),
                 close_reason = COALESCE(VALUES(close_reason), close_reason),
                 transcript_path = COALESCE(VALUES(transcript_path), transcript_path),
                 transcript_url = COALESCE(VALUES(transcript_url), transcript_url),
                 updated_at = CURRENT_TIMESTAMP""",
            (
                ticket.get("ticket_id"),
                ticket.get("guild_id"),
                ticket.get("channel_id"),
                str(ticket.get("creator_user_id") or "") or None,
                ticket.get("creator_username"),
                ticket.get("status"),
                ticket.get("subject"),
                ticket.get("category"),
                ticket.get("twitch_name"),
                ticket.get("closed_at"),
                ticket.get("closed_by_id"),
                ticket.get("closed_by_name"),
                ticket.get("close_reason"),
                ticket.get("transcript_path"),
                ticket.get("transcript_url"),
            ),
        )
        conn.commit()


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None


def _ticket_filter_sql(
    q: str = "", categories: set[str] | None = None, status: str | None = None
) -> tuple[str, list[Any]]:
    q_like = f"%{q}%"
    clauses = [
        "(ticket_id LIKE ? OR subject LIKE ? OR creator_user_id LIKE ? OR creator_username LIKE ?)"
    ]
    params: list[Any] = [q_like, q_like, q_like, q_like]
    if status in {"open", "closed"}:
        clauses.append("LOWER(COALESCE(status, 'open')) = ?")
        params.append(status)
    if categories is not None:
        if not categories:
            clauses.append("1 = 0")
        else:
            category_values = set(categories)
            if "discord" in categories:
                category_values.add("Discord Support")
            if "twitch" in categories:
                category_values.add("Twitch Support")
            if "general" in categories:
                category_values.add("Allgemeiner Support")
            if "admin" in categories:
                category_values.add("Admin Ticket")
            placeholders = ",".join("?" * len(category_values))
            clauses.append(f"COALESCE(category, 'general') IN ({placeholders})")
            params.extend(sorted(category_values))
    return " AND ".join(clauses), params


def list_tickets(
    q: str = "",
    limit: int = 200,
    offset: int = 0,
    categories: set[str] | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    where_sql, params = _ticket_filter_sql(q, categories, status)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM tickets
                WHERE {where_sql}
                ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_tickets(
    q: str = "", categories: set[str] | None = None, status: str | None = None
) -> int:
    where_sql, params = _ticket_filter_sql(q, categories, status)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM tickets WHERE {where_sql}",
            params,
        ).fetchone()
        return int(row["total"] if row else 0)


def list_tickets_for_user(
    guild_id: str,
    user_id: str,
    limit: int = 100,
    offset: int = 0,
    categories: set[str] | None = None,
) -> list[dict[str, Any]]:
    clauses = ["creator_user_id = ?"]
    params: list[Any] = [str(user_id)]
    if categories is not None:
        if not categories:
            clauses.append("1 = 0")
        else:
            category_values = set(categories)
            if "discord" in categories:
                category_values.add("Discord Support")
            if "twitch" in categories:
                category_values.add("Twitch Support")
            if "general" in categories:
                category_values.add("Allgemeiner Support")
            if "admin" in categories:
                category_values.add("Admin Ticket")
            placeholders = ",".join("?" * len(category_values))
            clauses.append(f"COALESCE(category, 'general') IN ({placeholders})")
            params.extend(sorted(category_values))
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM tickets
                WHERE {" AND ".join(clauses)}
                ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_tickets_for_user(
    guild_id: str,
    user_id: str,
    categories: set[str] | None = None,
) -> int:
    clauses = ["creator_user_id = ?"]
    params: list[Any] = [str(user_id)]
    if categories is not None:
        if not categories:
            clauses.append("1 = 0")
        else:
            placeholders = ",".join("?" * len(categories))
            clauses.append(f"COALESCE(category, 'general') IN ({placeholders})")
            params.extend(sorted(categories))
    with _connect() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM tickets WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return int(row["total"] if row else 0)


def get_ticket_stats_for_user(guild_id: str, user_id: str) -> dict:
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS ticket_count,
                      COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open_tickets,
                      COALESCE(SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END), 0) AS closed_tickets,
                      MAX(updated_at) AS last_ticket_at
               FROM tickets
               WHERE creator_user_id = ?""",
            (str(user_id),),
        ).fetchone()
        return (
            dict(row)
            if row
            else {
                "ticket_count": 0,
                "open_tickets": 0,
                "closed_tickets": 0,
                "last_ticket_at": None,
            }
        )


# ══════════ Ticket Messages ══════════


def add_ticket_message(
    ticket_id: str,
    author_id: str,
    author_name: str,
    content: str,
    source: str = "discord",
    discord_message_id: str | None = None,
) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO ticket_messages
               (ticket_id, author_id, author_name, content, source, discord_message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, author_id, author_name, content, source, discord_message_id),
        )
        message_row_id = conn.conn.insert_id()
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ticket_messages WHERE id = ?",
            (message_row_id,),
        ).fetchone()
        return dict(row)


def get_ticket_messages(ticket_id: str, limit: int = 500) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY created_at ASC LIMIT ?",
            (ticket_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ══════════ Ticket Logs ══════════


def insert_ticket_log(data: dict[str, Any]) -> None:
    level = data.get("level") or data.get("action") or data.get("event") or "info"
    message = data.get("message")
    if not message:
        user_name = data.get("user_name") or data.get("username") or "system"
        content = data.get("content") or ""
        message = f"{user_name}: {content}".strip(": ")

    with _connect() as conn:
        conn.execute(
            "INSERT INTO ticket_logs (ticket_id, level, message, data_json) VALUES (?, ?, ?, ?)",
            (
                data.get("ticket_id"),
                level,
                message,
                data.get("data_json") or json.dumps(data, ensure_ascii=False),
            ),
        )
        conn.commit()


def list_logs_for_ticket(ticket_id: str, limit: int = 200) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ticket_logs WHERE ticket_id = ? ORDER BY created_at ASC LIMIT ?",
            (ticket_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ══════════ Close Reasons ══════════


def list_close_reasons(guild_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM close_reasons WHERE guild_id = ? ORDER BY sort_order, id",
            (guild_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_close_reason(guild_id: str, label: str, sort_order: int = 0) -> dict:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO close_reasons (guild_id, label, sort_order) VALUES (?, ?, ?)",
            (guild_id, label, sort_order),
        )
        reason_id = conn.conn.insert_id()
        conn.commit()
        row = conn.execute(
            "SELECT * FROM close_reasons WHERE id = ?",
            (reason_id,),
        ).fetchone()
        return dict(row)


def update_close_reason(
    reason_id: int, label: str | None = None, sort_order: int | None = None
) -> None:
    parts, params = [], []
    if label is not None:
        parts.append("label = ?")
        params.append(label)
    if sort_order is not None:
        parts.append("sort_order = ?")
        params.append(sort_order)
    if not parts:
        return
    params.append(reason_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE close_reasons SET {', '.join(parts)} WHERE id = ?", params
        )
        conn.commit()


def delete_close_reason(reason_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM close_reasons WHERE id = ?", (reason_id,))
        conn.commit()
