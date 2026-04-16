from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
OLD_DB_DIR = ROOT_DIR / "OLD DATABASE"
WEB_LOGS_DIR = ROOT_DIR / "web_logs"
DB_PATH = WEB_LOGS_DIR / "data" / "pumbot.db"
BACKUP_DIR = WEB_LOGS_DIR / "data" / "backups"
SCHEMA_PATH = WEB_LOGS_DIR / "models.sql"


def load_json(name: str) -> dict:
    path = OLD_DB_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def backup_database() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"pumbot-before-old-import-{datetime.now():%Y%m%d-%H%M%S}.db"

    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(backup_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    return backup_path


def clear_database(conn: sqlite3.Connection) -> None:
    tables = [
        "ticket_messages",
        "ticket_logs",
        "tickets",
        "selfrole_mappings",
        "selfrole_panels",
        "warnings",
        "birthdays",
        "counting_user_stats",
        "counting_state",
        "auto_publisher_channels",
        "server_stats",
        "log_channels",
        "twitch_config",
        "guild_config",
        "roles",
        "users",
        "close_reasons",
    ]
    conn.execute("PRAGMA foreign_keys=OFF")
    for table in tables:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sqlite_sequence")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()


def seed_default_role(conn: sqlite3.Connection) -> None:
    env_path = ROOT_DIR / ".env"
    guild_id = "1441169067326177405"
    role_id = "1441253029432262787"

    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if key == "DISCORD_GUILD_ID" and value:
                guild_id = value
            elif key == "DEFAULT_ADMIN_ROLE_ID" and value:
                role_id = value

    conn.execute(
        """
        INSERT INTO roles (guild_id, discord_role_id, role_name, permissions)
        VALUES (?, ?, ?, ?)
        """,
        (guild_id, role_id, "Admin", json.dumps(["admin"])),
    )
    conn.commit()


def import_birthdays(conn: sqlite3.Connection) -> int:
    data = load_json("birthdays.json")
    inserted = 0

    for guild_id, payload in data.items():
        cfg = payload.get("_config", {})
        config_map = {
            "birthday_channel_id": cfg.get("channel_id"),
            "birthday_list_channel_id": cfg.get("list_channel_id"),
            "birthday_list_message_id": cfg.get("list_message_id"),
        }
        for key, value in config_map.items():
            if value is None:
                continue
            conn.execute(
                """
                INSERT INTO guild_config (guild_id, config_key, config_value)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, config_key) DO UPDATE SET config_value = excluded.config_value
                """,
                (str(guild_id), key, str(value)),
            )

        for user_id, birthday in payload.items():
            if user_id.startswith("_"):
                continue
            conn.execute(
                """
                INSERT INTO birthdays (guild_id, user_id, day, month, year, last_congrats)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id),
                    str(user_id),
                    int(birthday["day"]),
                    int(birthday["month"]),
                    birthday.get("year"),
                    birthday.get("last_congrats"),
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def import_counting(conn: sqlite3.Connection) -> tuple[int, int]:
    data = load_json("counting.json").get("guilds", {})
    state_count = 0
    stats_count = 0

    for guild_id, payload in data.items():
        conn.execute(
            """
            INSERT INTO counting_state (guild_id, channel_id, last_number, last_user_id, highscore)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(guild_id),
                str(payload["channel_id"]) if payload.get("channel_id") is not None else None,
                int(payload.get("last_number", 0)),
                str(payload["last_user_id"]) if payload.get("last_user_id") is not None else None,
                int(payload.get("highscore", 0)),
            ),
        )
        state_count += 1

        for user_id, stats in payload.get("users", {}).items():
            conn.execute(
                """
                INSERT INTO counting_user_stats
                (guild_id, user_id, correct, fails, best_streak, current_streak)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id),
                    str(user_id),
                    int(stats.get("correct", 0)),
                    int(stats.get("fails", 0)),
                    int(stats.get("best_streak", 0)),
                    int(stats.get("current_streak", 0)),
                ),
            )
            stats_count += 1

    conn.commit()
    return state_count, stats_count


def import_auto_publisher(conn: sqlite3.Connection) -> int:
    data = load_json("auto_publisher.json").get("guilds", {})
    inserted = 0

    for guild_id, payload in data.items():
        for channel_id in payload.get("channels", []):
            conn.execute(
                """
                INSERT INTO auto_publisher_channels (guild_id, channel_id)
                VALUES (?, ?)
                """,
                (str(guild_id), str(channel_id)),
            )
            inserted += 1

    conn.commit()
    return inserted


def import_selfroles(conn: sqlite3.Connection) -> tuple[int, int]:
    data = load_json("selfroles.json")
    panel_count = 0
    mapping_count = 0

    for guild_id, panels in data.items():
        for message_id, payload in panels.items():
            cursor = conn.execute(
                """
                INSERT INTO selfrole_panels (guild_id, message_id, channel_id, title, max_roles)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(guild_id),
                    str(message_id),
                    str(payload["channel_id"]),
                    payload.get("title") or "Selfrole Panel",
                    int(payload.get("max_roles", 0)),
                ),
            )
            panel_id = cursor.lastrowid
            panel_count += 1

            for emoji, role_id in payload.get("roles", {}).items():
                conn.execute(
                    """
                    INSERT INTO selfrole_mappings (panel_id, emoji, role_id)
                    VALUES (?, ?, ?)
                    """,
                    (panel_id, emoji, str(role_id)),
                )
                mapping_count += 1

    conn.commit()
    return panel_count, mapping_count


def import_server_stats(conn: sqlite3.Connection) -> int:
    data = load_json("server_stats.json").get("guilds", {})
    inserted = 0

    for guild_id, payload in data.items():
        category_id = payload.get("category_id")
        for stat_key, channel_id in payload.get("stats", {}).items():
            conn.execute(
                """
                INSERT INTO server_stats (guild_id, category_id, stat_key, channel_id)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(guild_id),
                    str(category_id) if category_id is not None else None,
                    str(stat_key),
                    str(channel_id),
                ),
            )
            inserted += 1

    conn.commit()
    return inserted


def import_log_channels(conn: sqlite3.Connection) -> int:
    data = load_json("logs_config.json").get("guilds", {})
    inserted = 0

    for guild_id, payload in data.items():
        for log_type, channel_id in payload.get("channels", {}).items():
            conn.execute(
                """
                INSERT INTO log_channels (guild_id, log_type, channel_id)
                VALUES (?, ?, ?)
                """,
                (str(guild_id), str(log_type), str(channel_id)),
            )
            inserted += 1

    conn.commit()
    return inserted


def import_twitch_config(conn: sqlite3.Connection) -> int:
    data = load_json("announcement.json")
    inserted = 0

    for guild_id, payload in data.items():
        twitch = payload.get("_twitch")
        if not twitch:
            continue
        conn.execute(
            """
            INSERT INTO twitch_config (guild_id, channel_id, last_stream_id)
            VALUES (?, ?, ?)
            """,
            (
                str(guild_id),
                str(twitch["channel_id"]) if twitch.get("channel_id") is not None else None,
                str(twitch["last_stream_id"]) if twitch.get("last_stream_id") is not None else None,
            ),
        )
        inserted += 1

    conn.commit()
    return inserted


def import_warnings(conn: sqlite3.Connection) -> int:
    data = load_json("warnings.json")
    inserted = 0

    for guild_id, users in data.items():
        for user_id, warnings in users.items():
            for warning in warnings:
                conn.execute(
                    """
                    INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(guild_id),
                        str(user_id),
                        str(warning["moderator_id"]),
                        warning.get("reason"),
                        warning.get("timestamp") or datetime.now().isoformat(),
                    ),
                )
                inserted += 1

    conn.commit()
    return inserted


def main() -> None:
    if not OLD_DB_DIR.exists():
        raise SystemExit(f"Old database directory not found: {OLD_DB_DIR}")
    if not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(DB_PATH).close()

    backup_path = backup_database()

    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_schema(conn)
        clear_database(conn)
        seed_default_role(conn)

        birthday_count = import_birthdays(conn)
        counting_state_count, counting_stats_count = import_counting(conn)
        auto_publisher_count = import_auto_publisher(conn)
        selfrole_panel_count, selfrole_mapping_count = import_selfroles(conn)
        server_stats_count = import_server_stats(conn)
        log_channel_count = import_log_channels(conn)
        twitch_count = import_twitch_config(conn)
        warning_count = import_warnings(conn)
    finally:
        conn.close()

    print(f"Backup created: {backup_path}")
    print("Import completed:")
    print(f"  birthdays: {birthday_count}")
    print(f"  counting_state: {counting_state_count}")
    print(f"  counting_user_stats: {counting_stats_count}")
    print(f"  auto_publisher_channels: {auto_publisher_count}")
    print(f"  selfrole_panels: {selfrole_panel_count}")
    print(f"  selfrole_mappings: {selfrole_mapping_count}")
    print(f"  server_stats: {server_stats_count}")
    print(f"  log_channels: {log_channel_count}")
    print(f"  twitch_config: {twitch_count}")
    print(f"  warnings: {warning_count}")


if __name__ == "__main__":
    main()
