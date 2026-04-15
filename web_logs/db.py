from __future__ import annotations

import json
import sqlite3
from typing import Any

try:
    from .config import BASE_DIR, Config, ensure_dirs
except ImportError:
    from config import BASE_DIR, Config, ensure_dirs


# TODO: Auf MySQL Datenbank umstellen und mit Bot verknüpfen
def _connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(Config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    schema_path = BASE_DIR / "models.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with _connect() as conn:
        conn.executescript(sql)
        conn.commit()


# -------- Users ----------
def user_count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"])


def create_user(username: str, password_hash: str, role: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, password_hash, role),
        )
        conn.commit()


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


def set_user_role(user_id: int, role: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


# -------- Tickets ----------
def upsert_ticket(ticket: dict[str, Any]) -> None:
    """
    Erwartet keys wie:
    ticket_id, guild_id, channel_id, creator_user_id, status, subject, closed_at, transcript_path
    """
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tickets (
              ticket_id, guild_id, channel_id, creator_user_id, status, subject, closed_at, transcript_path,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(ticket_id) DO UPDATE SET
              guild_id=excluded.guild_id,
              channel_id=excluded.channel_id,
              creator_user_id=excluded.creator_user_id,
              status=excluded.status,
              subject=excluded.subject,
              closed_at=excluded.closed_at,
              transcript_path=excluded.transcript_path,
              updated_at=datetime('now')
            """,
            (
                ticket.get("ticket_id"),
                ticket.get("guild_id"),
                ticket.get("channel_id"),
                str(ticket.get("creator_user_id") or ""),
                ticket.get("status"),
                ticket.get("subject"),
                ticket.get("closed_at"),
                ticket.get("transcript_path"),
            ),
        )
        conn.commit()


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        return dict(row) if row else None


def list_tickets(q: str = "", limit: int = 200) -> list[dict[str, Any]]:
    q_like = f"%{q}%"
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tickets
            WHERE ticket_id LIKE ? OR subject LIKE ? OR creator_user_id LIKE ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (q_like, q_like, q_like, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# -------- Logs (optional) ----------
def insert_log(data: dict[str, Any]) -> None:
    level = data.get("level") or data.get("action") or data.get("event") or "info"
    message = data.get("message")
    if not message:
        user_name = data.get("user_name") or data.get("username") or "system"
        content = data.get("content") or ""
        message = f"{user_name}: {content}".strip(": ")

    with _connect() as conn:
        conn.execute(
            "INSERT INTO logs (ticket_id, level, message, data_json) VALUES (?, ?, ?, ?)",
            (
                data.get("ticket_id"),
                level,
                message,
                data.get("data_json") or json.dumps(data, ensure_ascii=False),
            ),
        )
        conn.commit()


def list_logs_for_ticket(ticket_id: str, limit: int = 200) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM logs WHERE ticket_id = ? ORDER BY id DESC LIMIT ?",
            (ticket_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
