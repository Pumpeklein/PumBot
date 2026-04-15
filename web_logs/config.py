from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
DB_PATH = DATA_DIR / "logs.db"

load_dotenv()


def get_env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None or val.strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return val


class Config:
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
    LOG_API_KEY: str = os.getenv("LOG_API_KEY", "")
    BASE_URL: str = os.getenv("BASE_URL", "http://127.0.0.1:8080")
    PORT: int = int(os.getenv("PORT", "8080"))

    DB_PATH = DB_PATH
    DATA_DIR = DATA_DIR
    TRANSCRIPTS_DIR = TRANSCRIPTS_DIR


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
