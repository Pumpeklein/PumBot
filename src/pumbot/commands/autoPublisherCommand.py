from __future__ import annotations

from typing import List

import discord
from discord.ext import commands
from discord import app_commands

from src.pumbot import config
from src.pumbot.bot import logger


class AutoPublisherCog(commands.Cog):
    """Automatisches Veröffentlichen von Nachrichten in Announcement-Channels."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self._cache: dict[int, list[int]] = {}

    async def _get_channels(self, guild_id: int) -> List[int]:
        if guild_id in self._cache:
            return self._cache[guild_id]
        raw = await self.api.get_auto_publisher_channels(str(guild_id))
        channels = [int(c) for c in raw] if raw else []
        self._cache[guild_id] = channels
        return channels

    def _invalidate_cache(self, guild_id: int) -> None:
        self._cache.pop(guild_id, None)

    autopublisher = app_commands.Group(
        name="autopublisher",
        description="Konfiguriere automatische Veröffentlichungen in Announcement-Channels.",
    )

    @autopublisher.command(
        name="add",
        description="Fügt einen Announcement-Channel zum Auto-Publisher hinzu.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autopublisher_add(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )

        is_news = False
        try:
            if hasattr(channel, "is_news") and callable(getattr(channel, "is_news")):
                is_news = channel.is_news()
        except Exception:
            logger.exception("Fehler bei is_news Prüfung")

        if not is_news:
            return await interaction.response.send_message(
                f"{channel.mention} ist kein Announcement-/News-Channel. "
                "Auto-Publisher funktioniert nur in Announcement-Channels.",
                ephemeral=True,
            )

        await self.api.add_auto_publisher_channel(str(guild.id), str(channel.id))
        self._invalidate_cache(guild.id)

        await interaction.response.send_message(
            f"{channel.mention} wurde zum Auto-Publisher hinzugefügt.\n"
            "Neue Nachrichten werden automatisch veröffentlicht.",
            ephemeral=True,
        )

    @autopublisher.command(
        name="remove", description="Entfernt einen Channel aus dem Auto-Publisher.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def autopublisher_remove(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )

        channels = await self._get_channels(guild.id)
        if channel.id not in channels:
            return await interaction.response.send_message(
                f"{channel.mention} ist aktuell nicht im Auto-Publisher registriert.",
                ephemeral=True,
            )

        await self.api.remove_auto_publisher_channel(str(guild.id), str(channel.id))
        self._invalidate_cache(guild.id)

        await interaction.response.send_message(
            f"{channel.mention} wurde aus dem Auto-Publisher entfernt.", ephemeral=True,
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
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )

        channels_ids = await self._get_channels(guild.id)
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
            if message.author.bot or not message.guild:
                return

            channels = await self._get_channels(message.guild.id)
            if message.channel.id not in channels:
                return

            is_news = False
            try:
                if hasattr(message.channel, "is_news") and callable(
                    getattr(message.channel, "is_news")
                ):
                    is_news = message.channel.is_news()
            except Exception:
                pass

            if not is_news:
                return

            try:
                await message.publish()
                logger.info(
                    "Auto-Publisher: Nachricht %s in #%s veröffentlicht",
                    message.id, message.channel.name,
                )
            except discord.Forbidden:
                logger.warning(
                    "Auto-Publisher: Keine Berechtigung in #%s", message.channel.name,
                )
            except discord.HTTPException:
                logger.exception(
                    "Auto-Publisher: HTTP-Fehler in #%s", message.channel.name,
                )
        except Exception:
            logger.exception("Fehler im Auto-Publisher on_message-Handler")


async def setup(bot: commands.Bot):
    cog = AutoPublisherCog(bot)
    await bot.add_cog(cog)

    guild_obj = discord.Object(id=config.GUILD_ID)
    bot.tree.add_command(cog.autopublisher, guild=guild_obj)
