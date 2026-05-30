from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("discord_bot")


class MessageSyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _sync_channel(
        self,
        guild_id: str,
        channel: discord.TextChannel,
        limit: int | None,
    ) -> int:
        batch: list[dict] = []
        total = 0
        async for message in channel.history(limit=limit, oldest_first=True):
            if message.author.bot:
                continue
            if isinstance(message.author, discord.Member) and hasattr(self.bot, "_upsert_member"):
                await self.bot._upsert_member(message.author, status="active")
            batch.append(self.bot.message_payload(message))
            if len(batch) >= 100:
                result = await self.bot.api.upsert_guild_messages(guild_id, batch)
                total += int((result or {}).get("synced") or len(batch))
                batch = []
        if batch:
            result = await self.bot.api.upsert_guild_messages(guild_id, batch)
            total += int((result or {}).get("synced") or len(batch))
        return total

    @app_commands.command(
        name="messagesync",
        description="Importiert Nachrichten aus einem Kanal oder allen Textkanälen ins Dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        kanal="Optionaler Kanal. Ohne Angabe wird der aktuelle Kanal genutzt.",
        alle="Alle Textkanäle synchronisieren.",
        limit="Maximale Nachrichten pro Kanal. Leer lassen für alles.",
    )
    async def messagesync(
        self,
        interaction: discord.Interaction,
        kanal: Optional[discord.TextChannel] = None,
        alle: bool = False,
        limit: Optional[int] = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message("Dieser Command funktioniert nur auf einem Server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_id = str(interaction.guild.id)
        per_channel_limit = max(1, min(limit, 100000)) if limit else None
        channels: list[discord.TextChannel]
        if alle:
            me = interaction.guild.me
            channels = [
                channel
                for channel in interaction.guild.text_channels
                if me is not None and channel.permissions_for(me).read_message_history
            ]
        else:
            selected = kanal or interaction.channel
            if not isinstance(selected, discord.TextChannel):
                await interaction.followup.send("Bitte wähle einen Textkanal aus.", ephemeral=True)
                return
            channels = [selected]
        if not channels:
            await interaction.followup.send("Keine lesbaren Textkanäle gefunden.", ephemeral=True)
            return

        synced = 0
        failed: list[str] = []
        for channel in channels:
            try:
                synced += await self._sync_channel(guild_id, channel, per_channel_limit)
            except discord.Forbidden:
                failed.append(channel.name)
            except discord.HTTPException:
                logger.exception("Message-Sync für #%s fehlgeschlagen", channel.name)
                failed.append(channel.name)

        suffix = f" Fehlgeschlagen: {', '.join(failed[:5])}" if failed else ""
        await interaction.followup.send(
            f"Message-Sync fertig: {synced} Nachrichten aus {len(channels)} Kanal/Kanälen gespeichert.{suffix}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageSyncCog(bot))
