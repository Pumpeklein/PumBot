from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any

from src.pumbot.storage import db
from src.pumbot.storage.config import TRANSCRIPTS_DIR, ensure_dirs
from src.pumbot.utils.datetime_format import format_berlin_datetime

logger = logging.getLogger("discord_bot.api_client")

_TRANSCRIPT_DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?"
)


def _format_transcript_dates(markup: str) -> str:
    return _TRANSCRIPT_DATETIME.sub(
        lambda match: format_berlin_datetime(match.group(0), fallback=match.group(0)),
        markup,
    )


def _render_transcript_html(data: dict[str, Any]) -> str:
    markup = (data.get("transcript_html") or "").strip()
    if markup:
        return _format_transcript_dates(markup)
    text = data.get("transcript_text") or ""
    if text:
        return _format_transcript_dates(f"<pre>{html.escape(text)}</pre>")
    return ""


class ApiClient:
    """Datenzugriff der Cogs.

    Früher lief das als HTTP-Client gegen das mitlaufende Flask-Panel. Das Panel
    ist inzwischen ein eigener Next.js-Dienst, deshalb greifen die Methoden nun
    direkt auf die Datenbank zu. Namen und Rückgabewerte bleiben unverändert,
    damit die Cogs nichts merken.

    pymysql blockiert, deshalb läuft jeder Aufruf über einen Worker-Thread.
    """

    @staticmethod
    async def _call(func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as error:  # eine kaputte Abfrage darf den Bot nicht stoppen
            logger.error("Datenbankaufruf %s fehlgeschlagen: %s", func.__name__, error)
            return None

    async def close(self) -> None:
        """Kompatibilität: früher wurde hier die HTTP-Session geschlossen."""

    # ── Config ──

    async def get_config(self, guild_id: str, key: str) -> str | None:
        return await self._call(db.get_config, guild_id, key)

    async def set_config(self, guild_id: str, key: str, value: str) -> None:
        await self._call(db.set_config, guild_id, key, value)

    # ── Mitglieder ──

    async def sync_guild_members(
        self, guild_id: str, members: list[dict], mark_missing_left: bool = True
    ) -> dict | None:
        return await self._call(
            db.sync_guild_members, guild_id, members, mark_missing_left=mark_missing_left
        )

    async def upsert_guild_member(
        self, guild_id: str, user_id: str, data: dict
    ) -> dict | None:
        return await self._call(db.upsert_guild_member, guild_id, {**data, "user_id": user_id})

    async def mark_guild_member_left(self, guild_id: str, user_id: str) -> None:
        await self._call(db.mark_guild_member_left, guild_id, user_id)

    # ── Nachrichten ──

    async def upsert_guild_message(self, guild_id: str, data: dict) -> dict | None:
        return await self._call(db.upsert_guild_message, guild_id, data)

    async def upsert_guild_messages(
        self, guild_id: str, messages: list[dict], *, insert_only: bool = False
    ) -> dict | None:
        return await self._call(
            db.upsert_guild_messages, guild_id, messages, insert_only=insert_only
        )

    async def mark_guild_message_deleted(
        self, guild_id: str, channel_id: str, message_id: str
    ) -> None:
        await self._call(db.mark_guild_message_deleted, guild_id, channel_id, message_id)

    # ── Geburtstage ──

    async def get_birthdays(self, guild_id: str) -> list:
        return await self._call(db.get_birthdays, guild_id) or []

    async def get_birthday(self, guild_id: str, user_id: str) -> dict | None:
        return await self._call(db.get_birthday, guild_id, user_id)

    async def set_birthday(
        self, guild_id: str, user_id: str, day: int, month: int, year: int | None = None
    ) -> None:
        await self._call(db.set_birthday, guild_id, user_id, day, month, year)

    async def delete_birthday(self, guild_id: str, user_id: str) -> None:
        await self._call(db.delete_birthday, guild_id, user_id)

    async def get_birthdays_today(self, guild_id: str) -> list:
        return await self._call(db.get_birthdays_today, guild_id) or []

    async def mark_birthday_congrats(self, guild_id: str, user_id: str) -> None:
        await self._call(db.mark_birthday_congrats, guild_id, user_id)

    # ── Bot-Nachrichten ──

    async def get_bot_messages(self, guild_id: str, message_type: str | None = None) -> list:
        return await self._call(db.list_bot_messages, guild_id, message_type) or []

    async def upsert_bot_message(
        self,
        guild_id: str,
        message_type: str,
        message_id: str,
        channel_id: str | None = None,
        meta_key: str | None = None,
    ) -> dict | None:
        return await self._call(
            db.upsert_bot_message,
            guild_id,
            message_type,
            message_id,
            channel_id=channel_id,
            meta_key=meta_key,
        )

    async def delete_bot_message(
        self, guild_id: str, message_type: str, message_id: str
    ) -> None:
        await self._call(db.delete_bot_message, guild_id, message_type, message_id)

    # ── Verwarnungen ──

    async def get_warnings(self, guild_id: str, user_id: str) -> list:
        return await self._call(db.get_warnings, guild_id, user_id) or []

    async def add_warning(
        self, guild_id: str, user_id: str, moderator_id: str, reason: str
    ) -> dict | None:
        return await self._call(db.add_warning, guild_id, user_id, moderator_id, reason)

    async def remove_warning(self, guild_id: str, warning_id: int) -> None:
        await self._call(db.remove_warning, warning_id)

    async def clear_warnings(self, guild_id: str, user_id: str) -> None:
        await self._call(db.clear_warnings, guild_id, user_id)

    # ── Counting ──

    async def get_counting(self, guild_id: str) -> dict | None:
        return await self._call(db.get_counting, guild_id)

    async def set_counting(self, guild_id: str, **kwargs: Any) -> None:
        await self._call(db.set_counting, guild_id, **kwargs)

    async def get_counting_stats(self, guild_id: str, user_id: str) -> dict | None:
        return await self._call(db.get_counting_stats, guild_id, user_id)

    async def set_counting_stats(self, guild_id: str, user_id: str, **kwargs: Any) -> None:
        await self._call(db.set_counting_stats, guild_id, user_id, **kwargs)

    async def get_counting_leaderboard(self, guild_id: str, limit: int = 10) -> list:
        return await self._call(db.get_counting_leaderboard, guild_id, limit) or []

    # ── Auto Publisher ──

    async def get_auto_publisher_channels(self, guild_id: str) -> list:
        return await self._call(db.get_auto_publisher_channels, guild_id) or []

    async def add_auto_publisher_channel(self, guild_id: str, channel_id: str) -> None:
        await self._call(db.add_auto_publisher_channel, guild_id, channel_id)

    async def remove_auto_publisher_channel(self, guild_id: str, channel_id: str) -> None:
        await self._call(db.remove_auto_publisher_channel, guild_id, channel_id)

    # ── Selfroles ──

    async def get_selfrole_panel(self, guild_id: str, message_id: str) -> dict | None:
        return await self._call(db.get_selfrole_panel, message_id)

    async def get_all_selfrole_panels(self, guild_id: str) -> list:
        return await self._call(db.get_all_selfrole_panels, guild_id) or []

    async def create_selfrole_panel(
        self,
        guild_id: str,
        message_id: str,
        channel_id: str,
        title: str,
        max_roles: int,
        roles: dict,
    ) -> dict | None:
        return await self._call(
            db.create_selfrole_panel, guild_id, message_id, channel_id, title, max_roles, roles
        )

    async def add_selfrole_mapping(
        self, guild_id: str, message_id: str, emoji: str, role_id: str
    ) -> None:
        await self._call(db.add_selfrole_mapping, message_id, emoji, role_id)

    async def remove_selfrole_mapping(self, guild_id: str, message_id: str, emoji: str) -> None:
        await self._call(db.remove_selfrole_mapping, message_id, emoji)

    async def delete_selfrole_panel(self, guild_id: str, message_id: str) -> None:
        await self._call(db.delete_selfrole_panel, message_id)

    # ── Server-Statistiken ──

    async def get_server_stats(self, guild_id: str) -> dict:
        return await self._call(db.get_server_stats, guild_id) or {}

    async def set_server_stats(self, guild_id: str, data: dict) -> None:
        stats = {key: value for key, value in data.items() if key != "category_id"}
        await self._call(db.set_server_stats, guild_id, data.get("category_id"), stats)

    # ── Log-Kanäle ──

    async def get_log_channel(self, guild_id: str, log_type: str) -> str | None:
        return await self._call(db.get_log_channel, guild_id, log_type)

    async def set_log_channel(self, guild_id: str, log_type: str, channel_id: str) -> None:
        await self._call(db.set_log_channel, guild_id, log_type, channel_id)

    async def get_all_log_channels(self, guild_id: str) -> dict:
        return await self._call(db.get_all_log_channels, guild_id) or {}

    # ── Twitch ──

    async def get_twitch_config(self, guild_id: str) -> dict | None:
        return await self._call(db.get_twitch_config, guild_id)

    async def set_twitch_config(self, guild_id: str, **kwargs: Any) -> None:
        await self._call(db.set_twitch_config, guild_id, **kwargs)

    async def remove_twitch_config(self, guild_id: str) -> None:
        await self._call(db.remove_twitch_config, guild_id)

    # ── Tickets ──

    async def upsert_ticket(self, data: dict) -> dict | None:
        if not data.get("ticket_id"):
            logger.error("upsert_ticket ohne ticket_id")
            return None
        await self._call(db.upsert_ticket, data)
        return {"ok": True, "ticket_id": data["ticket_id"]}

    async def get_ticket(self, ticket_id: str) -> dict | None:
        return await self._call(db.get_ticket, ticket_id)

    async def list_tickets(self, q: str = "", limit: int = 200) -> list:
        return await self._call(db.list_tickets, q=q, limit=limit) or []

    async def add_ticket_message(
        self,
        ticket_id: str,
        author_id: str,
        author_name: str,
        content: str,
        source: str = "discord",
        discord_message_id: str | None = None,
    ) -> dict | None:
        return await self._call(
            db.add_ticket_message,
            ticket_id=ticket_id,
            author_id=author_id,
            author_name=author_name,
            content=content,
            source=source,
            discord_message_id=discord_message_id,
        )

    async def get_ticket_messages(self, ticket_id: str) -> list:
        return await self._call(db.get_ticket_messages, ticket_id) or []

    async def send_ticket_log(self, **kwargs: Any) -> None:
        if not kwargs.get("ticket_id"):
            logger.error("send_ticket_log ohne ticket_id")
            return
        await self._call(db.insert_ticket_log, kwargs)

    async def send_ticket_archive(self, **data: Any) -> None:
        """Schließt ein Ticket ab: Transkript sichern und Ticket fortschreiben."""
        ticket_id = str(data.get("ticket_id") or "").strip()
        if not ticket_id:
            logger.error("send_ticket_archive ohne ticket_id")
            return

        transcript_rel = ""
        markup = _render_transcript_html(data)
        if markup:
            ensure_dirs()
            target = TRANSCRIPTS_DIR / f"{ticket_id}.html"
            await asyncio.to_thread(target.write_text, markup, "utf-8")
            transcript_rel = f"data/transcripts/{ticket_id}.html"

        await self._call(
            db.upsert_ticket,
            {
                "ticket_id": ticket_id,
                "guild_id": data.get("guild_id"),
                "channel_id": data.get("channel_id") or ticket_id,
                "creator_user_id": str(
                    data.get("creator_user_id") or data.get("creator_id") or ""
                ),
                "creator_username": data.get("creator_name") or data.get("creator_username"),
                "status": data.get("status") or "closed",
                "subject": data.get("subject") or data.get("category_label") or "",
                "category": data.get("category") or data.get("category_label") or "",
                "closed_at": data.get("closed_at") or "",
                "closed_by_id": data.get("closed_by_id"),
                "closed_by_name": data.get("closed_by_name"),
                "close_reason": data.get("close_reason"),
                "transcript_path": transcript_rel or None,
                "transcript_url": data.get("transcript_url"),
            },
        )

    # ── Schließungsgründe ──

    async def get_close_reasons(self, guild_id: str) -> list:
        return await self._call(db.list_close_reasons, guild_id) or []
