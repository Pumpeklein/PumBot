from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"

load_dotenv()

DEFAULT_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "1441169067326177405")
DEFAULT_ADMIN_ROLE_ID = os.getenv("DEFAULT_ADMIN_ROLE_ID", "1441253029432262787")


class Config:
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
    SESSION_LIFETIME_DAYS: int = max(1, int(os.getenv("SESSION_LIFETIME_DAYS", "30")))
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

    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_NAME: str = os.getenv("DB_NAME", "")
    DB_USER: str = os.getenv("DB_USER", "")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_CHARSET: str = os.getenv("DB_CHARSET", "utf8mb4")

    # Minecraft-Server (PumpeCraft Plugin) – eigene Datenbank
    MC_DB_HOST: str = os.getenv("MC_DB_HOST", "")
    MC_DB_PORT: int = int(os.getenv("MC_DB_PORT", "3306"))
    MC_DB_NAME: str = os.getenv("MC_DB_NAME", "")
    MC_DB_USER: str = os.getenv("MC_DB_USER", "")
    MC_DB_PASSWORD: str = os.getenv("MC_DB_PASSWORD", "")
    MC_DB_CHARSET: str = os.getenv("MC_DB_CHARSET", "utf8mb4")
    MC_DB_CONNECT_TIMEOUT: int = int(os.getenv("MC_DB_CONNECT_TIMEOUT", "10"))
    MC_DB_READ_TIMEOUT: int = int(os.getenv("MC_DB_READ_TIMEOUT", "20"))
    MC_SERVER_NAME: str = os.getenv("MC_SERVER_NAME", "PumpeCraft")
    MC_SERVER_ADDRESS: str = os.getenv("MC_SERVER_ADDRESS", "")
    # Skin-Köpfe (externer Renderer) – leer lassen um Avatare zu deaktivieren
    MC_HEAD_BASE_URL: str = os.getenv("MC_HEAD_BASE_URL", "https://mc-heads.net/avatar")
    # Namensauflösung über die Mojang-API für Spieler ohne Moderations-Eintrag
    MC_NAME_LOOKUP: bool = os.getenv("MC_NAME_LOOKUP", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    MC_NAME_LOOKUP_TIMEOUT: float = float(os.getenv("MC_NAME_LOOKUP_TIMEOUT", "2.5"))
    MC_NAME_LOOKUP_MAX: int = int(os.getenv("MC_NAME_LOOKUP_MAX", "25"))

    DATA_DIR = DATA_DIR
    TRANSCRIPTS_DIR = TRANSCRIPTS_DIR


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
