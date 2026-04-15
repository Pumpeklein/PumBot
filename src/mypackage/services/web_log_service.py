from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _headers() -> dict:
    key = os.getenv("LOG_API_KEY")
    return {"X-API-KEY": key} if key else {}


async def send_web_log(
    session: aiohttp.ClientSession,
    *,
    ticket_id: str,
    user_name: str,
    action: str,
    content: str,
    created_at: Optional[str] = None,
) -> None:
    url = os.getenv("LOG_WEB_URL", "http://127.0.0.1:8080/api/logs")

    payload = {
        "created_at": created_at or _now_iso(),
        "ticket_id": ticket_id,
        "user_name": user_name,
        "action": action,
        "content": content,
    }

    async with session.post(url, json=payload, headers=_headers()) as resp:
        if resp.status < 200 or resp.status >= 300:
            text = await resp.text()
            raise RuntimeError(f"[WEB_LOG] HTTP {resp.status}: {text}")


async def send_ticket_archive(
    session: aiohttp.ClientSession,
    *,
    ticket_id: str,
    channel_name: str,
    category_label: str,
    creator_id: str | None,
    creator_name: str | None,
    opened_at: str | None,
    closed_at: str,
    closed_by_id: str,
    closed_by_name: str,
    close_reason: str,
    transcript_url: str | None,
    transcript_text: str,
) -> None:
    url = os.getenv("LOG_ARCHIVE_URL", "http://127.0.0.1:8080/api/tickets/close")

    payload = {
        "ticket_id": ticket_id,
        "channel_name": channel_name,
        "category_label": category_label,
        "creator_id": creator_id,
        "creator_name": creator_name,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "closed_by_id": closed_by_id,
        "closed_by_name": closed_by_name,
        "close_reason": close_reason,
        "transcript_url": transcript_url,
        "transcript_text": transcript_text,
    }

    async with session.post(url, json=payload, headers=_headers()) as resp:
        if resp.status < 200 or resp.status >= 300:
            text = await resp.text()
            raise RuntimeError(f"[TICKET_ARCHIVE] HTTP {resp.status}: {text}")
