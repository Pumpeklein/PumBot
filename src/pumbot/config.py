from __future__ import annotations

import os
from typing import Final

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int = 0) -> int:
    value = os.getenv(name)
    if value and value.isdigit():
        return int(value)
    return default


GUILD_ID: Final[int] = _env_int("DISCORD_GUILD_ID")

WELCOME_BANNER_URL: str | None = None

DISCORD_TOKEN_ENV: Final[str] = "DISCORD_TOKEN"
DEFAULT_PREFIX: Final[str] = "!"
OWNER_IDS: set[int] = set()
