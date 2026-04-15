from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import discord
from discord.ext import commands
from discord import app_commands

from src.pumbot import config
from src.pumbot.bot import logger


BASE_DIR = Path(__file__).resolve().parent.parent
AUTO_PUB_FILE = BASE_DIR / "database" / "auto_publisher.json"


def _load_data() -> Dict[str, Any]:
    try:
        if not AUTO_PUB_FILE.exists():
            return {"guilds": {}}
        with AUTO_PUB_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Fehler beim Laden der Auto-Publisher-Datei")
        return {"guilds": {}}


def _save_data(data: Dict[str, Any]) -> None:
    """Speichert die Auto-Publisher-Konfiguration in JSON."""
    try:
        AUTO_PUB_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUTO_PUB_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        logger.exception("Fehler beim Speichern der Auto-Publisher-Datei")


def _get_guild_cfg(guild_id: int) -> Dict[str, Any]:
    data = _load_data()
    return data.get("guilds", {}).get(str(guild_id), {})


def _set_guild_cfg(guild_id: int, cfg: Dict[str, Any]) -> None:
    data = _load_data()
    guilds = data.setdefault("guilds", {})
    guilds[str(guild_id)] = cfg
    _save_data(data)


class AutoPublisherCog(commands.Cog):
    """Automatisches Veröffentlichen von Nachrichten in Announcement-Channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    autopublisher = app_commands.Group(
        name="autopublisher",
        description="Konfiguriere automatische Veröffentlichungen in Announcement-Channels.",
    )

    # -------------- Hilfsfunktionen -------------- #

    def _get_channels(self, guild_id: int) -> List[int]:
        cfg = _get_guild_cfg(guild_id)
        channels = cfg.get("channels", [])
        if not isinstance(channels, list):
            return []
        # sicherstellen, dass es ints sind
        result: List[int] = []
        for ch_id in channels:
            try:
                result.append(int(ch_id))
            except (TypeError, ValueError):
                continue
        return result

    def _set_channels(self, guild_id: int, channels: List[int]) -> None:
        cfg = _get_guild_cfg(guild_id)
        cfg["channels"] = list({int(c) for c in channels})  # duplicates entfernen
        _set_guild_cfg(guild_id, cfg)

    def _add_channel(self, guild_id: int, channel_id: int) -> None:
        channels = self._get_channels(guild_id)
        if channel_id not in channels:
            channels.append(channel_id)
        self._set_channels(guild_id, channels)

    def _remove_channel(self, guild_id: int, channel_id: int) -> bool:
        channels = self._get_channels(guild_id)
        if channel_id not in channels:
            return False
        channels = [c for c in channels if c != channel_id]
        self._set_channels(guild_id, channels)
        return True

    @autopublisher.command(
        name="add",
        description="Fügt einen Announcement-Channel zum Auto-Publisher hinzu.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autopublisher_add(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        is_news = False
        try:
            # neuere libs: TextChannel.is_news()
            if hasattr(channel, "is_news") and callable(getattr(channel, "is_news")):
                is_news = channel.is_news()
        except Exception:
            logger.exception("Fehler bei der Prüfung, ob Channel ein News-Channel ist")

        if not is_news:
            return await interaction.response.send_message(
                f"{channel.mention} ist kein Announcement-/News-Channel. "
                "Auto-Publisher funktioniert nur in Announcement-Channels.",
                ephemeral=True,
            )

        self._add_channel(guild.id, channel.id)

        await interaction.response.send_message(
            f"{channel.mention} wurde zum Auto-Publisher hinzugefügt.\n"
            "Neue Nachrichten werden automatisch veröffentlicht (sofern der Bot die Berechtigung hat).",
            ephemeral=True,
        )

    @autopublisher.command(
        name="remove",
        description="Entfernt einen Channel aus dem Auto-Publisher.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autopublisher_remove(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        removed = self._remove_channel(guild.id, channel.id)
        if not removed:
            return await interaction.response.send_message(
                f"{channel.mention} ist aktuell nicht im Auto-Publisher registriert.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"{channel.mention} wurde aus dem Auto-Publisher entfernt.",
            ephemeral=True,
        )

    @autopublisher.command(
        name="list",
        description="Zeigt alle Channels, in denen automatisch veröffentlicht wird.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autopublisher_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        channels_ids = self._get_channels(guild.id)
        if not channels_ids:
            return await interaction.response.send_message(
                "Es sind aktuell **keine** Channels für den Auto-Publisher konfiguriert.",
                ephemeral=True,
            )

        lines = []
        for ch_id in channels_ids:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                lines.append(f"- {ch.mention} (`{ch.id}`)")
            else:
                lines.append(f"- Unbekannter Channel (`{ch_id}`)")

        await interaction.response.send_message(
            "Folgende Channels werden automatisch veröffentlicht:\n" + "\n".join(lines),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        try:
            if message.author.bot:
                return
            if not message.guild:
                return

            guild_id = message.guild.id
            channel_id = message.channel.id

            channels = self._get_channels(guild_id)
            if channel_id not in channels:
                return  # Channel nicht registriert

            channel = message.channel

            is_news = False
            try:
                if hasattr(channel, "is_news") and callable(
                    getattr(channel, "is_news")
                ):
                    is_news = channel.is_news()
            except Exception:
                logger.exception(
                    "Fehler bei der Prüfung, ob Channel ein News-Channel ist"
                )

            if not is_news:
                return

            try:
                await message.publish()
                logger.info(
                    "Auto-Publisher: Nachricht %s in #%s (%s) veröffentlicht",
                    message.id,
                    channel.name,
                    channel.id,
                )
            except discord.Forbidden:
                logger.warning(
                    "Auto-Publisher: Keine Berechtigung, Nachricht %s in #%s (%s) zu veröffentlichen",
                    message.id,
                    channel.name,
                    channel.id,
                )
            except discord.HTTPException:
                logger.exception(
                    "Auto-Publisher: HTTP-Fehler beim Veröffentlichen von Nachricht %s in #%s (%s)",
                    message.id,
                    channel.name,
                    channel.id,
                )

        except Exception:
            logger.exception("Fehler im Auto-Publisher on_message-Handler")


async def setup(bot: commands.Bot):
    cog = AutoPublisherCog(bot)
    await bot.add_cog(cog)

    guild_obj = discord.Object(id=config.GUILD_ID)
    bot.tree.add_command(cog.autopublisher, guild=guild_obj)
