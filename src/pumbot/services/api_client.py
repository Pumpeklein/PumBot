from __future__ import annotations

import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("discord_bot.api_client")


class ApiClient:
    """Async HTTP client for the bot to talk to the Flask API."""

    def __init__(self) -> None:
        self.base_url = os.getenv("API_BASE_URL", "http://127.0.0.1:3000")
        self.api_key = os.getenv("LOG_API_KEY", "")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        try:
            async with session.request(method, url, headers=self._headers(), **kwargs) as resp:
                if resp.status == 404:
                    return None
                if resp.status >= 400:
                    text = await resp.text()
                    logger.error("API %s %s -> %d: %s", method, path, resp.status, text)
                    return None
                return await resp.json()
        except Exception as e:
            logger.error("API request failed: %s %s - %s", method, path, e)
            return None

    async def get(self, path: str, **params: Any) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, data: dict | None = None) -> Any:
        return await self._request("POST", path, json=data)

    async def put(self, path: str, data: dict | None = None) -> Any:
        return await self._request("PUT", path, json=data)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Config ──

    async def get_config(self, guild_id: str, key: str) -> str | None:
        result = await self.get(f"/api/guild/{guild_id}/config/{key}")
        return result.get("value") if result else None

    async def set_config(self, guild_id: str, key: str, value: str) -> None:
        await self.put(f"/api/guild/{guild_id}/config/{key}", {"value": value})

    async def sync_guild_members(
        self, guild_id: str, members: list[dict], mark_missing_left: bool = True
    ) -> dict | None:
        return await self.post(
            f"/api/guild/{guild_id}/members/sync",
            {"members": members, "mark_missing_left": mark_missing_left},
        )

    async def upsert_guild_member(
        self, guild_id: str, user_id: str, data: dict
    ) -> dict | None:
        return await self.put(f"/api/guild/{guild_id}/members/{user_id}", data)

    async def mark_guild_member_left(self, guild_id: str, user_id: str) -> None:
        await self.post(f"/api/guild/{guild_id}/members/{user_id}/left")

    async def upsert_guild_message(self, guild_id: str, data: dict) -> dict | None:
        return await self.post(f"/api/guild/{guild_id}/messages", data)

    async def upsert_guild_messages(self, guild_id: str, messages: list[dict]) -> dict | None:
        return await self.post(f"/api/guild/{guild_id}/messages/bulk", {"messages": messages})

    async def mark_guild_message_deleted(
        self, guild_id: str, channel_id: str, message_id: str
    ) -> None:
        await self.post(f"/api/guild/{guild_id}/messages/{channel_id}/{message_id}/delete")

    # ── Birthdays ──

    async def get_birthdays(self, guild_id: str) -> list:
        return await self.get(f"/api/guild/{guild_id}/birthdays") or []

    async def get_birthday(self, guild_id: str, user_id: str) -> dict | None:
        return await self.get(f"/api/guild/{guild_id}/birthdays/{user_id}")

    async def set_birthday(
        self, guild_id: str, user_id: str, day: int, month: int, year: int | None = None
    ) -> None:
        await self.put(
            f"/api/guild/{guild_id}/birthdays/{user_id}",
            {"day": day, "month": month, "year": year},
        )

    async def delete_birthday(self, guild_id: str, user_id: str) -> None:
        await self.delete(f"/api/guild/{guild_id}/birthdays/{user_id}")

    async def get_birthdays_today(self, guild_id: str) -> list:
        return await self.get(f"/api/guild/{guild_id}/birthdays/today") or []

    async def mark_birthday_congrats(self, guild_id: str, user_id: str) -> None:
        await self.post(f"/api/guild/{guild_id}/birthdays/{user_id}/congrats")

    # ── Warnings ──

    async def get_bot_messages(
        self, guild_id: str, message_type: str | None = None
    ) -> list:
        params: dict[str, Any] = {}
        if message_type is not None:
            params["message_type"] = message_type
        return await self.get(f"/api/guild/{guild_id}/bot_messages", **params) or []

    async def upsert_bot_message(
        self,
        guild_id: str,
        message_type: str,
        message_id: str,
        channel_id: str | None = None,
        meta_key: str | None = None,
    ) -> dict | None:
        data: dict[str, Any] = {}
        if channel_id is not None:
            data["channel_id"] = channel_id
        if meta_key is not None:
            data["meta_key"] = meta_key
        return await self.put(
            f"/api/guild/{guild_id}/bot_messages/{message_type}/{message_id}",
            data,
        )

    async def delete_bot_message(
        self, guild_id: str, message_type: str, message_id: str
    ) -> None:
        await self.delete(
            f"/api/guild/{guild_id}/bot_messages/{message_type}/{message_id}"
        )

    async def get_warnings(self, guild_id: str, user_id: str) -> list:
        return await self.get(f"/api/guild/{guild_id}/warnings/{user_id}") or []

    async def add_warning(
        self, guild_id: str, user_id: str, moderator_id: str, reason: str
    ) -> dict | None:
        return await self.post(
            f"/api/guild/{guild_id}/warnings",
            {"user_id": user_id, "moderator_id": moderator_id, "reason": reason},
        )

    async def remove_warning(self, guild_id: str, warning_id: int) -> None:
        await self.delete(f"/api/guild/{guild_id}/warnings/{warning_id}")

    async def clear_warnings(self, guild_id: str, user_id: str) -> None:
        await self.delete(f"/api/guild/{guild_id}/warnings/user/{user_id}")

    # ── Counting ──

    async def get_counting(self, guild_id: str) -> dict | None:
        return await self.get(f"/api/guild/{guild_id}/counting")

    async def set_counting(self, guild_id: str, **kwargs: Any) -> None:
        await self.put(f"/api/guild/{guild_id}/counting", kwargs)

    async def get_counting_stats(self, guild_id: str, user_id: str) -> dict | None:
        return await self.get(f"/api/guild/{guild_id}/counting/stats/{user_id}")

    async def set_counting_stats(self, guild_id: str, user_id: str, **kwargs: Any) -> None:
        await self.put(f"/api/guild/{guild_id}/counting/stats/{user_id}", kwargs)

    async def get_counting_leaderboard(self, guild_id: str, limit: int = 10) -> list:
        return await self.get(f"/api/guild/{guild_id}/counting/leaderboard", limit=limit) or []

    # ── Auto Publisher ──

    async def get_auto_publisher_channels(self, guild_id: str) -> list:
        return await self.get(f"/api/guild/{guild_id}/auto_publisher") or []

    async def add_auto_publisher_channel(self, guild_id: str, channel_id: str) -> None:
        await self.post(f"/api/guild/{guild_id}/auto_publisher", {"channel_id": channel_id})

    async def remove_auto_publisher_channel(self, guild_id: str, channel_id: str) -> None:
        await self.delete(f"/api/guild/{guild_id}/auto_publisher/{channel_id}")

    # ── Selfroles ──

    async def get_selfrole_panel(self, guild_id: str, message_id: str) -> dict | None:
        return await self.get(f"/api/guild/{guild_id}/selfroles/{message_id}")

    async def get_all_selfrole_panels(self, guild_id: str) -> list:
        return await self.get(f"/api/guild/{guild_id}/selfroles") or []

    async def create_selfrole_panel(
        self, guild_id: str, message_id: str, channel_id: str,
        title: str, max_roles: int, roles: dict,
    ) -> dict | None:
        return await self.post(f"/api/guild/{guild_id}/selfroles", {
            "message_id": message_id, "channel_id": channel_id,
            "title": title, "max_roles": max_roles, "roles": roles,
        })

    async def add_selfrole_mapping(
        self, guild_id: str, message_id: str, emoji: str, role_id: str
    ) -> None:
        await self.put(
            f"/api/guild/{guild_id}/selfroles/{message_id}/roles",
            {"emoji": emoji, "role_id": role_id},
        )

    async def remove_selfrole_mapping(
        self, guild_id: str, message_id: str, emoji: str
    ) -> None:
        await self.delete(f"/api/guild/{guild_id}/selfroles/{message_id}/roles/{emoji}")

    async def delete_selfrole_panel(self, guild_id: str, message_id: str) -> None:
        await self.delete(f"/api/guild/{guild_id}/selfroles/{message_id}")

    # ── Server Stats ──

    async def get_server_stats(self, guild_id: str) -> dict:
        return await self.get(f"/api/guild/{guild_id}/server_stats") or {}

    async def set_server_stats(self, guild_id: str, data: dict) -> None:
        await self.put(f"/api/guild/{guild_id}/server_stats", data)

    # ── Log Channels ──

    async def get_log_channel(self, guild_id: str, log_type: str) -> str | None:
        result = await self.get(f"/api/guild/{guild_id}/log_channels/{log_type}")
        return result.get("channel_id") if result else None

    async def set_log_channel(self, guild_id: str, log_type: str, channel_id: str) -> None:
        await self.put(
            f"/api/guild/{guild_id}/log_channels/{log_type}",
            {"channel_id": channel_id},
        )

    async def get_all_log_channels(self, guild_id: str) -> dict:
        return await self.get(f"/api/guild/{guild_id}/log_channels") or {}

    # ── Twitch Config ──

    async def get_twitch_config(self, guild_id: str) -> dict | None:
        return await self.get(f"/api/guild/{guild_id}/twitch_config")

    async def set_twitch_config(self, guild_id: str, **kwargs: Any) -> None:
        await self.put(f"/api/guild/{guild_id}/twitch_config", kwargs)

    async def remove_twitch_config(self, guild_id: str) -> None:
        await self.delete(f"/api/guild/{guild_id}/twitch_config")

    # ── Tickets ──

    async def upsert_ticket(self, data: dict) -> dict | None:
        return await self.post("/api/tickets", data)

    async def get_ticket(self, ticket_id: str) -> dict | None:
        return await self.get(f"/api/tickets/{ticket_id}")

    async def list_tickets(self, q: str = "", limit: int = 200) -> list:
        return await self.get("/api/tickets", q=q, limit=limit) or []

    async def add_ticket_message(
        self, ticket_id: str, author_id: str, author_name: str,
        content: str, source: str = "discord", discord_message_id: str | None = None,
    ) -> dict | None:
        return await self.post(f"/api/tickets/{ticket_id}/messages", {
            "author_id": author_id, "author_name": author_name,
            "content": content, "source": source,
            "discord_message_id": discord_message_id,
        })

    async def get_ticket_messages(self, ticket_id: str) -> list:
        return await self.get(f"/api/tickets/{ticket_id}/messages") or []

    # ── Ticket Logs (legacy compat) ──

    async def send_ticket_log(self, **kwargs: Any) -> None:
        await self.post("/api/ticket_logs", kwargs)

    async def send_ticket_archive(self, **kwargs: Any) -> None:
        await self.post("/api/tickets/close", kwargs)

    # ── Close Reasons ──

    async def get_close_reasons(self, guild_id: str) -> list:
        return await self.get(f"/api/guild/{guild_id}/close_reasons") or []
