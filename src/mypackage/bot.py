from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Final, Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from src.mypackage import config


LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)
logger.propagate = False

if logger.handlers:
    logger.handlers.clear()

formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

file_handler = logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logging.getLogger("discord.app_commands").setLevel(logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

TOKEN_ENV_NAME = getattr(config, "DISCORD_TOKEN_ENV", "DISCORD_TOKEN")
TOKEN: Final[str | None] = os.getenv(TOKEN_ENV_NAME) or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Discord Token fehlt (.env: DISCORD_TOKEN oder DISCORD_TOKEN_ENV)")

GUILD_ID_ENV_RAW = os.getenv("DISCORD_GUILD_ID")
GUILD_ID_ENV = int(GUILD_ID_ENV_RAW) if GUILD_ID_ENV_RAW and GUILD_ID_ENV_RAW.isdigit() else None
GUILD_ID_CFG = getattr(config, "GUILD_ID", None)
GUILD_ID: Optional[int] = GUILD_ID_ENV or (
    int(GUILD_ID_CFG)
    if isinstance(GUILD_ID_CFG, int) or (isinstance(GUILD_ID_CFG, str) and str(GUILD_ID_CFG).isdigit())
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
    "src.mypackage.commands.announcmentCommand",
    "src.mypackage.commands.birthdayCommand",
    "src.mypackage.commands.selfrolesCommand",
    "src.mypackage.commands.TicketSystemCommand",
    "src.mypackage.commands.userManagementCommand",
    "src.mypackage.commands.deleteCommand",
    "src.mypackage.commands.helpCommand",
    "src.mypackage.commands.willkommenCommand",
    "src.mypackage.commands.autoPublisherCommand",
    "src.mypackage.commands.serverStatsCommand",
    "src.mypackage.commands.countingCommand",
    "src.mypackage.commands.serverinfoCommand",
    "src.mypackage.commands.logsCommand",
]


async def reply_ephemeral(interaction: discord.Interaction, content: str) -> None:
    try:
        await interaction.response.send_message(content, ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(content, ephemeral=True)


class PumpeBot(commands.Bot):
    async def setup_hook(self) -> None:
        guild_obj = discord.Object(id=int(GUILD_ID)) if GUILD_ID is not None else None

        for ext in EXTENSIONS:
            await self.load_extension(ext)


        from src.mypackage.commands.TicketSystemCommand import TicketPanelView, TicketCloseView
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
        logger.info("Eingeloggt als %s (%s)", self.user, self.user.id if self.user else "unbekannt")


bot = PumpeBot(
    command_prefix=COMMAND_PREFIX,
    intents=intents,
    help_command=None,
)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await reply_ephemeral(interaction, "Dafür hast du keine Berechtigung.")
        return
    logger.exception("Unhandled app command error", exc_info=error)
    await reply_ephemeral(interaction, "Da ist ein Fehler passiert.")


async def main() -> None:
    try:
        async with bot:
            await bot.start(TOKEN)
    except Exception:
        logger.exception("Bot-Start fehlgeschlagen")
        raise


# TODO: Web-Interface mit starten
if __name__ == "__main__":
    asyncio.run(main())

