from __future__ import annotations

import json
import sqlite3
from typing import Any

try:
    from .config import BASE_DIR, Config, ensure_dirs, DEFAULT_GUILD_ID, DEFAULT_ADMIN_ROLE_ID
    from .datetime_format import berlin_today
except ImportError:
    from config import BASE_DIR, Config, ensure_dirs, DEFAULT_GUILD_ID, DEFAULT_ADMIN_ROLE_ID
    from datetime_format import berlin_today


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    _migrate_stale_tables()
    schema_path = BASE_DIR / "models.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with _connect() as conn:
        conn.executescript(sql)
        _ensure_columns(conn, "guild_members", {
            "roles_json": "TEXT",
            "presence_status": "TEXT",
            "activity_name": "TEXT",
            "activity_type": "TEXT",
            "status_updated_at": "TEXT",
        })
        conn.commit()
    _seed_default_roles()
    _seed_default_bot_messages()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _migrate_stale_tables() -> None:
    """Drop and let init_db recreate tables whose schema is outdated."""
    expected_columns = {
        "users": {"discord_id", "discord_username", "discord_avatar", "last_login"},
        "tickets": {"creator_username", "category", "closed_by_id", "closed_by_name", "close_reason", "transcript_url", "twitch_name"},
    }
    with _connect() as conn:
        for table, required_cols in expected_columns.items():
            existing = {
                row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not existing:
                continue  # table doesn't exist yet, will be created
            if not required_cols.issubset(existing):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                conn.commit()


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
                   ON CONFLICT(guild_id, message_type, message_id) DO UPDATE SET
                     channel_id = COALESCE(excluded.channel_id, bot_messages.channel_id),
                     updated_at = datetime('now')""",
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
               WHERE guild_id = ? AND config_key LIKE 'birthday_%'
               UNION
               SELECT 1
               FROM bot_messages
               WHERE guild_id = ? AND message_type = 'birthday_list'
               LIMIT 1""",
            (default_guild_id, default_guild_id, default_guild_id),
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
               WHERE config_key LIKE 'birthday_%'
               ORDER BY guild_id ASC
               LIMIT 1"""
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

def upsert_user(discord_id: str, discord_username: str, discord_avatar: str | None = None) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO users (discord_id, discord_username, discord_avatar, last_login)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(discord_id) DO UPDATE SET
                 discord_username = excluded.discord_username,
                 discord_avatar = excluded.discord_avatar,
                 last_login = datetime('now')""",
            (discord_id, discord_username, discord_avatar),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,)).fetchone()
        return dict(row)


def get_user_by_discord_id(discord_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,)).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY last_login DESC").fetchall()
        return [dict(r) for r in rows]


def _member_name_changed(existing: sqlite3.Row, member: dict[str, Any]) -> bool:
    return any(
        (existing[key] or "") != (member.get(key) or "")
        for key in ("username", "global_name", "display_name")
    )


def upsert_guild_member(guild_id: str, member: dict[str, Any]) -> dict:
    user_id = str(member["user_id"])
    username = str(member.get("username") or user_id)
    display_name = str(member.get("display_name") or member.get("global_name") or username)
    global_name = member.get("global_name")
    discriminator = member.get("discriminator")
    avatar_url = member.get("avatar_url")
    roles_json = json.dumps(member.get("roles") or [], ensure_ascii=False)
    is_bot = 1 if member.get("is_bot") else 0
    status = member.get("status") or "active"
    presence_status = member.get("presence_status")
    activity_name = member.get("activity_name")
    activity_type = member.get("activity_type")
    joined_at = member.get("joined_at")
    left_at = member.get("left_at")

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
                     new_username, new_global_name, new_display_name
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    guild_id,
                    user_id,
                    existing["username"],
                    existing["global_name"],
                    existing["display_name"],
                    username,
                    global_name,
                    display_name,
                ),
            )

        conn.execute(
            """INSERT INTO guild_members (
                 guild_id, user_id, username, global_name, display_name, discriminator,
                 avatar_url, roles_json, is_bot, status, presence_status, activity_name, activity_type,
                 status_updated_at, joined_at, left_at, first_seen_at,
                 last_seen_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, datetime('now'), datetime('now'), datetime('now'))
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                 username = excluded.username,
                 global_name = excluded.global_name,
                 display_name = excluded.display_name,
                 discriminator = excluded.discriminator,
                 avatar_url = excluded.avatar_url,
                 roles_json = excluded.roles_json,
                 is_bot = excluded.is_bot,
                 status = excluded.status,
                 presence_status = COALESCE(excluded.presence_status, guild_members.presence_status),
                 activity_name = COALESCE(excluded.activity_name, guild_members.activity_name),
                 activity_type = COALESCE(excluded.activity_type, guild_members.activity_type),
                 status_updated_at = CASE
                   WHEN excluded.presence_status IS NOT NULL THEN datetime('now')
                   ELSE guild_members.status_updated_at
                 END,
                 joined_at = COALESCE(excluded.joined_at, guild_members.joined_at),
                 left_at = excluded.left_at,
                 last_seen_at = datetime('now'),
                 updated_at = datetime('now')""",
            (
                guild_id,
                user_id,
                username,
                global_name,
                display_name,
                discriminator,
                avatar_url,
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
            display_name = str(member.get("display_name") or member.get("global_name") or username)
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
                         new_username, new_global_name, new_display_name
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        guild_id,
                        user_id,
                        existing["username"],
                        existing["global_name"],
                        existing["display_name"],
                        username,
                        member.get("global_name"),
                        display_name,
                    ),
                )
            conn.execute(
                """INSERT INTO guild_members (
                     guild_id, user_id, username, global_name, display_name, discriminator,
                     avatar_url, roles_json, is_bot, status, presence_status, activity_name, activity_type,
                     status_updated_at, joined_at, left_at, first_seen_at,
                     last_seen_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, datetime('now'), ?, NULL, datetime('now'), datetime('now'), datetime('now'))
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET
                     username = excluded.username,
                     global_name = excluded.global_name,
                     display_name = excluded.display_name,
                     discriminator = excluded.discriminator,
                     avatar_url = excluded.avatar_url,
                     roles_json = excluded.roles_json,
                     is_bot = excluded.is_bot,
                     status = 'active',
                     presence_status = COALESCE(excluded.presence_status, guild_members.presence_status),
                     activity_name = COALESCE(excluded.activity_name, guild_members.activity_name),
                     activity_type = COALESCE(excluded.activity_type, guild_members.activity_type),
                     status_updated_at = CASE
                       WHEN excluded.presence_status IS NOT NULL THEN datetime('now')
                       ELSE guild_members.status_updated_at
                     END,
                     joined_at = COALESCE(excluded.joined_at, guild_members.joined_at),
                     left_at = NULL,
                     last_seen_at = datetime('now'),
                     updated_at = datetime('now')""",
                (
                    guild_id,
                    user_id,
                    username,
                    member.get("global_name"),
                    display_name,
                    member.get("discriminator"),
                    member.get("avatar_url"),
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
                row["user_id"] for row in active_before if row["user_id"] not in seen_ids
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
    guild_id: str, q: str = "", status: str = "all"
) -> tuple[list[str], list[Any]]:
    clauses = ["guild_id = ?"]
    params: list[Any] = [guild_id]
    if status in {"active", "left"}:
        clauses.append("status = ?")
        params.append(status)
    if q:
        q_like = f"%{q}%"
        clauses.append(
            "(user_id LIKE ? OR username LIKE ? OR global_name LIKE ? OR display_name LIKE ?)"
        )
        params.extend([q_like, q_like, q_like, q_like])
    return clauses, params


def list_guild_members(
    guild_id: str,
    q: str = "",
    status: str = "all",
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    clauses, params = _guild_members_where(guild_id, q, status)
    params.append(limit)
    params.append(offset)
    joined_clauses = []
    for clause in clauses:
        if clause == "guild_id = ?":
            joined_clauses.append("gm.guild_id = ?")
        elif clause == "status = ?":
            joined_clauses.append("gm.status = ?")
        elif clause.startswith("(user_id LIKE"):
            joined_clauses.append(
                "(gm.user_id LIKE ? OR gm.username LIKE ? OR gm.global_name LIKE ? OR gm.display_name LIKE ?)"
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
                WHERE {' AND '.join(joined_clauses)}
                GROUP BY gm.id
                ORDER BY gm.status ASC, gm.display_name COLLATE NOCASE ASC
                LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def count_guild_members(guild_id: str, q: str = "", status: str = "all") -> int:
    clauses, params = _guild_members_where(guild_id, q, status)
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


def upsert_guild_message(guild_id: str, message: dict[str, Any]) -> dict:
    channel_id = str(message["channel_id"])
    message_id = str(message["message_id"])
    user_id = str(message["user_id"])
    with _connect() as conn:
        conn.execute(
            """INSERT INTO guild_messages (
                 guild_id, channel_id, channel_name, message_id, user_id, content,
                 attachment_count, jump_url, created_at, edited_at, deleted_at, synced_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(guild_id, channel_id, message_id) DO UPDATE SET
                 channel_name = excluded.channel_name,
                 user_id = excluded.user_id,
                 content = excluded.content,
                 attachment_count = excluded.attachment_count,
                 jump_url = excluded.jump_url,
                 created_at = excluded.created_at,
                 edited_at = excluded.edited_at,
                 deleted_at = COALESCE(excluded.deleted_at, guild_messages.deleted_at),
                 synced_at = datetime('now')""",
            (
                guild_id,
                channel_id,
                message.get("channel_name"),
                message_id,
                user_id,
                message.get("content"),
                int(message.get("attachment_count") or 0),
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


def upsert_guild_messages(guild_id: str, messages: list[dict[str, Any]]) -> dict:
    synced = 0
    with _connect() as conn:
        for message in messages:
            if not message.get("channel_id") or not message.get("message_id") or not message.get("user_id"):
                continue
            conn.execute(
                """INSERT INTO guild_messages (
                     guild_id, channel_id, channel_name, message_id, user_id, content,
                     attachment_count, jump_url, created_at, edited_at, deleted_at, synced_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(guild_id, channel_id, message_id) DO UPDATE SET
                     channel_name = excluded.channel_name,
                     user_id = excluded.user_id,
                     content = excluded.content,
                     attachment_count = excluded.attachment_count,
                     jump_url = excluded.jump_url,
                     created_at = excluded.created_at,
                     edited_at = excluded.edited_at,
                     deleted_at = COALESCE(excluded.deleted_at, guild_messages.deleted_at),
                     synced_at = datetime('now')""",
                (
                    guild_id,
                    str(message["channel_id"]),
                    message.get("channel_name"),
                    str(message["message_id"]),
                    str(message["user_id"]),
                    message.get("content"),
                    int(message.get("attachment_count") or 0),
                    message.get("jump_url"),
                    message.get("created_at"),
                    message.get("edited_at"),
                    message.get("deleted_at"),
                ),
            )
            synced += 1
        conn.commit()
    return {"synced": synced}


def mark_guild_message_deleted(guild_id: str, channel_id: str, message_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE guild_messages
               SET deleted_at = datetime('now'), synced_at = datetime('now')
               WHERE guild_id = ? AND channel_id = ? AND message_id = ?""",
            (guild_id, channel_id, message_id),
        )
        conn.commit()


def _guild_messages_where(
    guild_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
    q: str = "",
    include_deleted: bool = False,
) -> tuple[list[str], list[Any]]:
    clauses = ["gm.guild_id = ?"]
    params: list[Any] = [guild_id]
    if user_id:
        clauses.append("gm.user_id = ?")
        params.append(user_id)
    if channel_id:
        clauses.append("gm.channel_id = ?")
        params.append(channel_id)
    if q:
        clauses.append("(gm.content LIKE ? OR gm.channel_name LIKE ? OR m.display_name LIKE ?)")
        q_like = f"%{q}%"
        params.extend([q_like, q_like, q_like])
    if not include_deleted:
        clauses.append("gm.deleted_at IS NULL")
    return clauses, params


def list_guild_messages(
    guild_id: str,
    user_id: str | None = None,
    channel_id: str | None = None,
    q: str = "",
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    clauses, params = _guild_messages_where(guild_id, user_id, channel_id, q, include_deleted)
    params.extend([limit, offset])
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT gm.*, m.display_name, m.username, m.avatar_url, m.presence_status
                FROM guild_messages gm
                LEFT JOIN guild_members m
                  ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
                WHERE {' AND '.join(clauses)}
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
) -> int:
    clauses, params = _guild_messages_where(guild_id, user_id, channel_id, q, include_deleted)
    with _connect() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS total
                FROM guild_messages gm
                LEFT JOIN guild_members m
                  ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
                WHERE {' AND '.join(clauses)}""",
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
        return dict(row) if row else {
            "message_count": 0,
            "channel_count": 0,
            "last_message_at": None,
            "attachment_count": 0,
        }


def get_user_channel_message_stats(guild_id: str, user_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT channel_id, COALESCE(channel_name, channel_id) AS channel_name,
                      COUNT(*) AS message_count,
                      MAX(created_at) AS last_message_at
               FROM guild_messages
               WHERE guild_id = ? AND user_id = ? AND deleted_at IS NULL
               GROUP BY channel_id
               ORDER BY message_count DESC, channel_name COLLATE NOCASE ASC""",
            (guild_id, user_id),
        ).fetchall()
        return [dict(r) for r in rows]


def get_guild_message_overview(guild_id: str) -> dict:
    with _connect() as conn:
        totals = conn.execute(
            """SELECT COUNT(*) AS message_count,
                      COUNT(DISTINCT user_id) AS active_writers,
                      COUNT(DISTINCT channel_id) AS active_channels,
                      MAX(created_at) AS last_message_at
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL""",
            (guild_id,),
        ).fetchone()
        top_users = conn.execute(
            """SELECT gm.user_id, COUNT(*) AS message_count,
                      m.display_name, m.username, m.avatar_url
               FROM guild_messages gm
               LEFT JOIN guild_members m
                 ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
               WHERE gm.guild_id = ? AND gm.deleted_at IS NULL
               GROUP BY gm.user_id
               ORDER BY message_count DESC
               LIMIT 10""",
            (guild_id,),
        ).fetchall()
        top_channels = conn.execute(
            """SELECT channel_id, COALESCE(channel_name, channel_id) AS channel_name,
                      COUNT(*) AS message_count,
                      MAX(created_at) AS last_message_at
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL
               GROUP BY channel_id
               ORDER BY message_count DESC
               LIMIT 10""",
            (guild_id,),
        ).fetchall()
        return {
            "totals": dict(totals) if totals else {},
            "top_users": [dict(r) for r in top_users],
            "top_channels": [dict(r) for r in top_channels],
        }


def list_message_filter_users(guild_id: str, limit: int = 500) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT gm.user_id,
                      COUNT(*) AS message_count,
                      m.display_name,
                      m.username
               FROM guild_messages gm
               LEFT JOIN guild_members m
                 ON m.guild_id = gm.guild_id AND m.user_id = gm.user_id
               WHERE gm.guild_id = ? AND gm.deleted_at IS NULL
               GROUP BY gm.user_id
               ORDER BY COALESCE(m.display_name, m.username, gm.user_id) COLLATE NOCASE ASC
               LIMIT ?""",
            (guild_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_message_filter_channels(guild_id: str, limit: int = 500) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT channel_id,
                      COALESCE(channel_name, channel_id) AS channel_name,
                      COUNT(*) AS message_count
               FROM guild_messages
               WHERE guild_id = ? AND deleted_at IS NULL
               GROUP BY channel_id
               ORDER BY channel_name COLLATE NOCASE ASC
               LIMIT ?""",
            (guild_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ══════════ Roles & Permissions ══════════

ALL_PERMISSIONS = [
    "admin",
    "tickets.view", "tickets.reply", "tickets.close",
    "users.view", "users.warn", "users.ban", "users.timeout",
    "roles.manage",
    "config.manage",
    "logs.view", "logs.manage",
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


def get_role(role_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["permissions"] = json.loads(d.get("permissions") or "[]")
        return d


def create_role(guild_id: str, discord_role_id: str, role_name: str, permissions: list[str]) -> dict:
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


def update_role(role_id: int, role_name: str | None = None, permissions: list[str] | None = None) -> None:
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


def get_permissions_for_discord_roles(guild_id: str, discord_role_ids: list[str]) -> set[str]:
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
               ON CONFLICT(guild_id, config_key) DO UPDATE SET config_value = excluded.config_value""",
            (guild_id, key, value),
        )
        conn.commit()


def delete_config(guild_id: str, key: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM guild_config WHERE guild_id = ? AND config_key = ?", (guild_id, key)
        )
        conn.commit()


# ══════════ Birthdays ══════════

def get_birthdays(guild_id: str, limit: int | None = None, offset: int = 0) -> list[dict]:
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


def set_birthday(guild_id: str, user_id: str, day: int, month: int, year: int | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO birthdays (guild_id, user_id, day, month, year)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                 day = excluded.day, month = excluded.month, year = excluded.year""",
            (guild_id, user_id, day, month, year),
        )
        conn.commit()


def delete_birthday(guild_id: str, user_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
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
               ON CONFLICT(guild_id, message_type, message_id) DO UPDATE SET
                 channel_id = excluded.channel_id,
                 meta_key = COALESCE(excluded.meta_key, bot_messages.meta_key),
                 updated_at = datetime('now')""",
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
        conn.commit()
        row = conn.execute("SELECT * FROM warnings WHERE rowid = last_insert_rowid()").fetchone()
        return dict(row)


def remove_warning(warning_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM warnings WHERE id = ?", (warning_id,))
        conn.commit()


def clear_warnings(guild_id: str, user_id: str) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        conn.commit()
        return cursor.rowcount


def list_all_warnings(guild_id: str, limit: int = 200, offset: int = 0) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM warnings
               WHERE guild_id = ?
               ORDER BY created_at DESC
               LIMIT ? OFFSET ?""",
            (guild_id, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_warnings(guild_id: str, user_id: str | None = None) -> int:
    with _connect() as conn:
        if user_id:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM warnings WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM warnings WHERE guild_id = ?",
                (guild_id,),
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
                    f"UPDATE counting_state SET {', '.join(parts)} WHERE guild_id = ?", params
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
                    guild_id, user_id,
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


def get_counting_leaderboard(guild_id: str, limit: int = 10, offset: int = 0) -> list[dict]:
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
            "SELECT channel_id FROM auto_publisher_channels WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        return [row["channel_id"] for row in rows]


def add_auto_publisher_channel(guild_id: str, channel_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO auto_publisher_channels (guild_id, channel_id) VALUES (?, ?)",
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
            "SELECT emoji, role_id FROM selfrole_mappings WHERE panel_id = ?", (panel["id"],)
        ).fetchall()
        panel["roles"] = {m["emoji"]: m["role_id"] for m in mappings}
        return panel


def get_all_selfrole_panels(guild_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM selfrole_panels WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        panels = []
        for row in rows:
            panel = dict(row)
            mappings = conn.execute(
                "SELECT emoji, role_id FROM selfrole_mappings WHERE panel_id = ?",
                (panel["id"],),
            ).fetchall()
            panel["roles"] = {m["emoji"]: m["role_id"] for m in mappings}
            panels.append(panel)
        return panels


def create_selfrole_panel(
    guild_id: str, message_id: str, channel_id: str,
    title: str, max_roles: int, roles: dict[str, str],
) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO selfrole_panels (guild_id, message_id, channel_id, title, max_roles)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, message_id, channel_id, title, max_roles),
        )
        panel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
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
            "INSERT OR REPLACE INTO selfrole_mappings (panel_id, emoji, role_id) VALUES (?, ?, ?)",
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


def set_server_stats(guild_id: str, category_id: str | None, stats: dict[str, str]) -> None:
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
               ON CONFLICT(guild_id, log_type) DO UPDATE SET channel_id = excluded.channel_id""",
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
            "SELECT log_type, channel_id FROM log_channels WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        return {row["log_type"]: row["channel_id"] for row in rows}


# ══════════ Twitch Config ══════════

def get_twitch_config(guild_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM twitch_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return dict(row) if row else None


def set_twitch_config(guild_id: str, channel_id: str | None = None, last_stream_id: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO twitch_config (guild_id, channel_id, last_stream_id)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 channel_id = COALESCE(excluded.channel_id, twitch_config.channel_id),
                 last_stream_id = COALESCE(excluded.last_stream_id, twitch_config.last_stream_id)""",
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
               ON CONFLICT(ticket_id) DO UPDATE SET
                 guild_id = COALESCE(excluded.guild_id, tickets.guild_id),
                 channel_id = COALESCE(excluded.channel_id, tickets.channel_id),
                 creator_user_id = COALESCE(excluded.creator_user_id, tickets.creator_user_id),
                 creator_username = COALESCE(excluded.creator_username, tickets.creator_username),
                 status = COALESCE(excluded.status, tickets.status),
                 subject = COALESCE(excluded.subject, tickets.subject),
                 category = COALESCE(excluded.category, tickets.category),
                 twitch_name = COALESCE(excluded.twitch_name, tickets.twitch_name),
                 closed_at = COALESCE(excluded.closed_at, tickets.closed_at),
                 closed_by_id = COALESCE(excluded.closed_by_id, tickets.closed_by_id),
                 closed_by_name = COALESCE(excluded.closed_by_name, tickets.closed_by_name),
                 close_reason = COALESCE(excluded.close_reason, tickets.close_reason),
                 transcript_path = COALESCE(excluded.transcript_path, tickets.transcript_path),
                 transcript_url = COALESCE(excluded.transcript_url, tickets.transcript_url),
                 updated_at = datetime('now')""",
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


def list_tickets(q: str = "", limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
    q_like = f"%{q}%"
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM tickets
               WHERE ticket_id LIKE ? OR subject LIKE ? OR creator_user_id LIKE ? OR creator_username LIKE ?
               ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
            (q_like, q_like, q_like, q_like, limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_tickets(q: str = "") -> int:
    q_like = f"%{q}%"
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total FROM tickets
               WHERE ticket_id LIKE ? OR subject LIKE ? OR creator_user_id LIKE ? OR creator_username LIKE ?""",
            (q_like, q_like, q_like, q_like),
        ).fetchone()
        return int(row["total"] if row else 0)


def list_tickets_for_user(
    guild_id: str, user_id: str, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM tickets
               WHERE creator_user_id = ? AND (guild_id = ? OR guild_id IS NULL)
               ORDER BY updated_at DESC LIMIT ? OFFSET ?""",
            (str(user_id), str(guild_id), limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def count_tickets_for_user(guild_id: str, user_id: str) -> int:
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS total FROM tickets
               WHERE creator_user_id = ? AND (guild_id = ? OR guild_id IS NULL)""",
            (str(user_id), str(guild_id)),
        ).fetchone()
        return int(row["total"] if row else 0)


def get_ticket_stats_for_user(guild_id: str, user_id: str) -> dict:
    with _connect() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS ticket_count,
                      SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_tickets,
                      SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed_tickets,
                      MAX(updated_at) AS last_ticket_at
               FROM tickets
               WHERE creator_user_id = ? AND (guild_id = ? OR guild_id IS NULL)""",
            (str(user_id), str(guild_id)),
        ).fetchone()
        return dict(row) if row else {
            "ticket_count": 0,
            "open_tickets": 0,
            "closed_tickets": 0,
            "last_ticket_at": None,
        }


# ══════════ Ticket Messages ══════════

def add_ticket_message(
    ticket_id: str, author_id: str, author_name: str,
    content: str, source: str = "discord", discord_message_id: str | None = None,
) -> dict:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO ticket_messages
               (ticket_id, author_id, author_name, content, source, discord_message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ticket_id, author_id, author_name, content, source, discord_message_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ticket_messages WHERE rowid = last_insert_rowid()"
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
        conn.commit()
        row = conn.execute(
            "SELECT * FROM close_reasons WHERE rowid = last_insert_rowid()"
        ).fetchone()
        return dict(row)


def update_close_reason(reason_id: int, label: str | None = None, sort_order: int | None = None) -> None:
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
        conn.execute(f"UPDATE close_reasons SET {', '.join(parts)} WHERE id = ?", params)
        conn.commit()


def delete_close_reason(reason_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM close_reasons WHERE id = ?", (reason_id,))
        conn.commit()
