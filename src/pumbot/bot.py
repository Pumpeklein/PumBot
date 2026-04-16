from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from threading import Thread
from typing import Final, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from werkzeug.serving import make_server

from src.pumbot import config
from src.pumbot.services.api_client import ApiClient
from web_logs.app import create_app
from web_logs.config import Config as WebConfig


LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)
logger.propagate = False

if logger.handlers:
    logger.handlers.clear()

formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%d.%m.%Y • %H:%M Uhr",
)

file_handler = logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logging.getLogger("discord.app_commands").setLevel(logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

TOKEN_ENV_NAME = getattr(config, "DISCORD_TOKEN_ENV", "DISCORD_TOKEN")
TOKEN: Final[str | None] = os.getenv(TOKEN_ENV_NAME) or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError(
        "Discord Token fehlt (.env: DISCORD_TOKEN oder DISCORD_TOKEN_ENV)"
    )

GUILD_ID_ENV_RAW = os.getenv("DISCORD_GUILD_ID")
GUILD_ID_ENV = (
    int(GUILD_ID_ENV_RAW) if GUILD_ID_ENV_RAW and GUILD_ID_ENV_RAW.isdigit() else None
)
GUILD_ID_CFG = getattr(config, "GUILD_ID", None)
GUILD_ID: Optional[int] = GUILD_ID_ENV or (
    int(GUILD_ID_CFG)
    if isinstance(GUILD_ID_CFG, int)
    or (isinstance(GUILD_ID_CFG, str) and str(GUILD_ID_CFG).isdigit())
    else None
)

DEFAULT_PREFIX = getattr(config, "DEFAULT_PREFIX", "!")
COMMAND_PREFIX = commands.when_mentioned_or(DEFAULT_PREFIX)

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

EXTENSIONS: list[str] = [
    "src.pumbot.commands.announcmentCommand",
    "src.pumbot.commands.birthdayCommand",
    "src.pumbot.commands.selfrolesCommand",
    "src.pumbot.commands.TicketSystemCommand",
    "src.pumbot.commands.userManagementCommand",
    "src.pumbot.commands.deleteCommand",
    "src.pumbot.commands.helpCommand",
    "src.pumbot.commands.willkommenCommand",
    "src.pumbot.commands.autoPublisherCommand",
    "src.pumbot.commands.serverStatsCommand",
    "src.pumbot.commands.countingCommand",
    "src.pumbot.commands.serverinfoCommand",
    "src.pumbot.commands.logsCommand",
]


async def reply_ephemeral(interaction: discord.Interaction, content: str) -> None:
    try:
        await interaction.response.send_message(content, ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(content, ephemeral=True)


class PumpeBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api = ApiClient()

    async def setup_hook(self) -> None:
        guild_obj = discord.Object(id=int(GUILD_ID)) if GUILD_ID is not None else None

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        from src.pumbot.commands.TicketSystemCommand import (
            TicketPanelView,
            TicketCloseView,
        )

        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))

        if guild_obj is not None:
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info("Guild-Sync fertig (%d Commands).", len(synced))
        else:
            synced = await self.tree.sync()
            logger.info("Global-Sync fertig (%d Commands).", len(synced))

    async def on_ready(self) -> None:
        logger.info(
            "Eingeloggt als %s (%s)",
            self.user,
            self.user.id if self.user else "unbekannt",
        )


bot = PumpeBot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    help_command=None,
)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        await reply_ephemeral(interaction, "Dafür hast du keine Berechtigung.")
        return
    logger.exception("Unhandled app command error", exc_info=error)
    await reply_ephemeral(interaction, "Da ist ein Fehler passiert.")


class WebServerThread(Thread):
    def __init__(self, host: str, port: int, discord_bot=None):
        super().__init__(name="flask-web", daemon=True)
        self.host = host
        self.port = port
        self._bot = discord_bot
        self._server = None

    def run(self) -> None:
        flask_app = create_app()
        flask_app.config["DISCORD_BOT"] = self._bot
        self._server = make_server(self.host, self.port, flask_app, threaded=True)
        logger.info("Web-Interface gestartet auf http://%s:%s", self.host, self.port)
        self._server.serve_forever()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()


async def main() -> None:
    web_server = WebServerThread("127.0.0.1", WebConfig.PORT, discord_bot=bot)
    web_server.start()
    try:
        async with bot:
            await bot.start(TOKEN)
    except Exception:
        logger.exception("Bot-Start fehlgeschlagen")
        raise
    finally:
        await bot.api.close()
        web_server.shutdown()
        web_server.join(timeout=5)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
