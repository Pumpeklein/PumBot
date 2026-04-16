from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
DB_PATH = DATA_DIR / "pumbot.db"

load_dotenv()

DEFAULT_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1441169067326177405")
DEFAULT_ADMIN_ROLE_ID = os.getenv("DEFAULT_ADMIN_ROLE_ID", "1441253029432262787")


class Config:
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
    LOG_API_KEY: str = os.getenv("LOG_API_KEY", "")
    BASE_URL: str = os.getenv("BASE_URL", "http://127.0.0.1:3000")
    PORT: int = int(os.getenv("PORT", "3000"))

    # Discord OAuth2
    DISCORD_CLIENT_ID: str = os.getenv("DISCORD_CLIENT_ID", "")
    DISCORD_CLIENT_SECRET: str = os.getenv("DISCORD_CLIENT_SECRET", "")
    DISCORD_REDIRECT_URI: str = os.getenv(
        "DISCORD_REDIRECT_URI",
        os.getenv("BASE_URL", "http://127.0.0.1:3000") + "/auth/discord/callback",
    )
    DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

    DB_PATH = DB_PATH
    DATA_DIR = DATA_DIR
    TRANSCRIPTS_DIR = TRANSCRIPTS_DIR


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
