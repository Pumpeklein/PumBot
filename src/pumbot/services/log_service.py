from __future__ import annotations

import os
from datetime import datetime, timezone

import requests


LOG_WEB_URL = os.getenv("LOG_WEB_URL", "http://127.0.0.1:8080/api/logs")


def send_ticket_log(
    ticket_id: str,
    user_name: str,
    action: str,
    content: str,
) -> None:
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ticket_id": ticket_id,
        "user_name": user_name,
        "action": action,
        "content": content,
    }

    try:
        requests.post(LOG_WEB_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[LOG_SERVICE] Fehler beim Senden des Logs: {e}")
