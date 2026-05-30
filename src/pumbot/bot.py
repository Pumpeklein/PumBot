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
from web_logs.db import (
    mark_guild_member_left,
    mark_guild_message_deleted,
    sync_guild_members,
    upsert_guild_member,
    upsert_guild_message,
)


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
ENABLE_PRESENCE_INTENT = os.getenv("ENABLE_PRESENCE_INTENT", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True
intents.presences = ENABLE_PRESENCE_INTENT

EXTENSIONS: list[str] = [
    "src.pumbot.commands.announcmentCommand",
    "src.pumbot.commands.autoRoleCommand",
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
    "src.pumbot.commands.messageSyncCommand",
]


async def reply_ephemeral(interaction: discord.Interaction, content: str) -> None:
    try:
        await interaction.response.send_message(content, ephemeral=True)
    except discord.InteractionResponded:
        await interaction.followup.send(content, ephemeral=True)


class PumpeBot(commands.Bot):
    MEMBER_CHUNK_TIMEOUT_SECONDS = 20
    MEMBER_FETCH_TIMEOUT_SECONDS = 90

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api = ApiClient()
        self._member_sync_done = False

    @staticmethod
    def _avatar_url(member: discord.Member) -> str | None:
        return str(member.display_avatar.url) if member.display_avatar else None

    def _member_payload(
        self, member: discord.Member, status: str = "active"
    ) -> dict[str, object | None]:
        activity = next((a for a in member.activities if a), None)
        return {
            "user_id": str(member.id),
            "username": member.name,
            "global_name": member.global_name,
            "display_name": member.display_name,
            "discriminator": member.discriminator,
            "avatar_url": self._avatar_url(member),
            "banner_url": str(member.banner.url) if getattr(member, "banner", None) else None,
            "accent_color": int(member.accent_color.value) if getattr(member, "accent_color", None) else None,
            "locale": str(member.locale) if getattr(member, "locale", None) else None,
            "roles": [
                {"id": str(role.id), "name": role.name}
                for role in sorted(member.roles, key=lambda role: role.position, reverse=True)
                if role.name != "@everyone"
            ],
            "is_bot": member.bot,
            "status": status,
            "presence_status": str(member.status) if getattr(member, "status", None) else None,
            "activity_name": getattr(activity, "name", None) if activity else None,
            "activity_type": activity.type.name if activity else None,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        }

    @staticmethod
    def message_payload(
        message: discord.Message, original_content: str | None = None
    ) -> dict[str, object | None]:
        return {
            "channel_id": str(message.channel.id),
            "channel_name": getattr(message.channel, "name", str(message.channel.id)),
            "message_id": str(message.id),
            "user_id": str(message.author.id),
            "original_content": original_content,
            "content": message.content or "",
            "attachment_count": len(message.attachments),
            "jump_url": message.jump_url,
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "edited_at": message.edited_at.isoformat() if message.edited_at else None,
            "deleted_at": None,
        }

    async def _store_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        try:
            if isinstance(message.author, discord.Member):
                await self._upsert_member(message.author, status="active")
            await asyncio.to_thread(
                upsert_guild_message,
                str(message.guild.id),
                self.message_payload(message),
            )
        except Exception:
            logger.exception("Message-Upsert fuer %s fehlgeschlagen", message.id)

    async def _fetch_all_member_payloads(self, guild: discord.Guild) -> list[dict[str, object | None]]:
        payloads: list[dict[str, object | None]] = []
        async for member in guild.fetch_members(limit=None):
            payloads.append(self._member_payload(member))
        return payloads

    async def _sync_guild_members(self, guild: discord.Guild) -> bool:
        try:
            expected_count = guild.member_count or 0
            logger.info(
                "User-Sync fuer Guild %s gestartet. Erwartete Member laut Discord: %s.",
                guild.id,
                expected_count or "unbekannt",
            )
            if not getattr(guild, "chunked", False):
                logger.info(
                    "User-Sync fuer Guild %s: lade Memberliste von Discord.",
                    guild.id,
                )
            try:
                await asyncio.wait_for(
                    guild.chunk(cache=True),
                    timeout=self.MEMBER_CHUNK_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning(
                    "User-Sync fuer Guild %s: chunk timeout nach %s Sekunden.",
                    guild.id,
                    self.MEMBER_CHUNK_TIMEOUT_SECONDS,
                )
            except discord.HTTPException:
                logger.exception("User-Sync fuer Guild %s: chunk fehlgeschlagen.", guild.id)

            members = [self._member_payload(member) for member in guild.members]
            logger.info(
                "User-Sync fuer Guild %s: %s Member im Cache nach chunk.",
                guild.id,
                len(members),
            )

            if len(members) < expected_count:
                logger.info(
                    "User-Sync fuer Guild %s: hole vollstaendige Memberliste per REST.",
                    guild.id,
                )
                try:
                    fetched_members = await asyncio.wait_for(
                        self._fetch_all_member_payloads(guild),
                        timeout=self.MEMBER_FETCH_TIMEOUT_SECONDS,
                    )
                    logger.info(
                        "User-Sync fuer Guild %s: %s Member per REST geladen.",
                        guild.id,
                        len(fetched_members),
                    )
                    if len(fetched_members) > len(members):
                        members = fetched_members
                except TimeoutError:
                    logger.warning(
                        "User-Sync fuer Guild %s: REST fetch timeout nach %s Sekunden.",
                        guild.id,
                        self.MEMBER_FETCH_TIMEOUT_SECONDS,
                    )
                except discord.Forbidden:
                    logger.exception(
                        "User-Sync fuer Guild %s: REST fetch verboten. Pruefe Server Members Intent und Bot-Rechte.",
                        guild.id,
                    )
                except discord.HTTPException:
                    logger.exception("User-Sync fuer Guild %s: REST fetch fehlgeschlagen.", guild.id)

            if not members:
                logger.warning(
                    "User-Sync fuer Guild %s ohne Memberdaten beendet. Es wurde nichts gespeichert.",
                    guild.id,
                )
                return False

            has_complete_member_list = len(members) >= expected_count
            if not has_complete_member_list:
                logger.warning(
                    "User-Sync fuer Guild %s nur teilweise: %s/%s Member im Cache. "
                    "Fehlende User werden nicht als verlassen markiert.",
                    guild.id,
                    len(members),
                    expected_count,
                )
            result = await asyncio.to_thread(
                sync_guild_members,
                str(guild.id),
                members,
                has_complete_member_list,
            )
            logger.info(
                "User-Sync fuer Guild %s fertig: %s Member, %s als verlassen markiert.",
                guild.id,
                result.get("synced") if result else len(members),
                result.get("marked_left") if result else "unbekannt",
            )
            return True
        except Exception:
            logger.exception("User-Sync fuer Guild %s fehlgeschlagen", guild.id)
            return False

    async def _sync_all_guild_members_with_retries(self) -> None:
        guild_ids = [str(guild.id) for guild in self.guilds]
        if not guild_ids:
            logger.warning("User-Sync uebersprungen: Bot ist in keiner Guild.")
            return
        logger.info("Starte User-Sync fuer Guild(s): %s", ", ".join(guild_ids))
        for attempt in range(1, 4):
            results = [await self._sync_guild_members(guild) for guild in self.guilds]
            if results and all(results):
                self._member_sync_done = True
                return
            wait_seconds = attempt * 5
            logger.warning(
                "User-Sync nicht vollstaendig. Neuer Versuch %s/3 in %s Sekunden.",
                attempt + 1,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    async def _upsert_member(self, member: discord.Member, status: str = "active") -> None:
        try:
            await asyncio.to_thread(
                upsert_guild_member,
                str(member.guild.id),
                self._member_payload(member, status=status),
            )
            logger.info(
                "User %s (%s) fuer Guild %s als %s gespeichert.",
                member.display_name,
                member.id,
                member.guild.id,
                status,
            )
        except Exception:
            logger.exception("User-Upsert fuer %s fehlgeschlagen", member.id)

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
            try:
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info("Guild-Sync fertig (%d Commands).", len(synced))
                return
            except discord.Forbidden:
                logger.error(
                    "Guild-Sync fehlgeschlagen: Missing Access für Guild %s. "
                    "Prüfe DISCORD_GUILD_ID und ob der Bot auf diesem Server ist. "
                    "Versuche Global-Sync.",
                    GUILD_ID,
                )
            except discord.HTTPException:
                logger.exception(
                    "Guild-Sync fehlgeschlagen für Guild %s. Versuche Global-Sync.",
                    GUILD_ID,
                )

        try:
            synced = await self.tree.sync()
            logger.info("Global-Sync fertig (%d Commands).", len(synced))
        except discord.HTTPException:
            logger.exception("Global-Sync fehlgeschlagen. Bot startet ohne Command-Sync.")

    async def on_ready(self) -> None:
        logger.info(
            "Eingeloggt als %s (%s)",
            self.user,
            self.user.id if self.user else "unbekannt",
        )
        if self._member_sync_done:
            return
        await self._sync_all_guild_members_with_retries()

    async def on_member_join(self, member: discord.Member) -> None:
        await self._upsert_member(member, status="active")

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self._sync_guild_members(guild)

    async def on_member_remove(self, member: discord.Member) -> None:
        await self._upsert_member(member, status="left")
        await asyncio.to_thread(mark_guild_member_left, str(member.guild.id), str(member.id))

    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        if (
            before.name != after.name
            or before.global_name != after.global_name
            or before.display_name != after.display_name
            or before.display_avatar.url != after.display_avatar.url
            or [role.id for role in before.roles] != [role.id for role in after.roles]
        ):
            await self._upsert_member(after, status="active")

    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        if before.name == after.name and before.global_name == after.global_name:
            return
        for guild in self.guilds:
            member = guild.get_member(after.id)
            if member:
                await self._upsert_member(member, status="active")

    async def on_presence_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        if before.status != after.status or before.activities != after.activities:
            await self._upsert_member(after, status="active")

    async def on_message(self, message: discord.Message) -> None:
        await self._store_message(message)
        await self.process_commands(message)

    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        if not after.guild or after.author.bot:
            return
        try:
            await asyncio.to_thread(
                upsert_guild_message,
                str(after.guild.id),
                self.message_payload(after, original_content=before.content or ""),
            )
        except Exception:
            logger.exception("Message-Edit-Upsert fuer %s fehlgeschlagen", after.id)

    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild:
            return
        try:
            await asyncio.to_thread(
                mark_guild_message_deleted,
                str(message.guild.id),
                str(message.channel.id),
                str(message.id),
            )
        except Exception:
            logger.exception("Message-Delete-Markierung fuer %s fehlgeschlagen", message.id)


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
    web_server = WebServerThread("0.0.0.0", WebConfig.PORT, discord_bot=bot)
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
