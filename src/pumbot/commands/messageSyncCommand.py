from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("discord_bot")


class MessageSyncCog(commands.Cog):
    DEFAULT_LIMIT_PER_CHANNEL = 5000
    MAX_LIMIT_PER_CHANNEL = 100000
    BATCH_SIZE = 250

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._running_guilds: set[int] = set()

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
            batch.append(self.bot.message_payload(message))
            if len(batch) >= self.BATCH_SIZE:
                result = await self.bot.api.upsert_guild_messages(guild_id, batch)
                total += int((result or {}).get("synced") or len(batch))
                batch = []
                await asyncio.sleep(0)
        if batch:
            result = await self.bot.api.upsert_guild_messages(guild_id, batch)
            total += int((result or {}).get("synced") or len(batch))
        return total

    async def _run_sync(
        self,
        interaction: discord.Interaction,
        channels: list[discord.TextChannel],
        limit: int | None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return

        guild_id = str(guild.id)
        synced = 0
        failed: list[str] = []
        try:
            for channel in channels:
                try:
                    synced += await self._sync_channel(guild_id, channel, limit)
                except discord.Forbidden:
                    failed.append(channel.name)
                except discord.HTTPException:
                    logger.exception("Message-Sync für #%s fehlgeschlagen", channel.name)
                    failed.append(channel.name)
                except Exception:
                    logger.exception("Message-Sync für #%s unerwartet fehlgeschlagen", channel.name)
                    failed.append(channel.name)

            suffix = f" Fehlgeschlagen: {', '.join(failed[:5])}" if failed else ""
            with contextlib.suppress(Exception):
                await interaction.followup.send(
                    f"Message-Sync fertig: {synced} Nachrichten aus {len(channels)} Kanal/Kanälen gespeichert.{suffix}",
                    ephemeral=True,
                )
        except Exception:
            logger.exception("Message-Sync Hintergrundtask für Guild %s abgebrochen", guild_id)
            with contextlib.suppress(Exception):
                await interaction.followup.send(
                    "Message-Sync ist abgebrochen. Details stehen im Bot-Log.",
                    ephemeral=True,
                )
        finally:
            self._running_guilds.discard(guild.id)

    @app_commands.command(
        name="messagesync",
        description="Importiert Nachrichten aus einem Kanal oder allen Textkanälen ins Dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        kanal="Optionaler Kanal. Ohne Angabe wird der aktuelle Kanal genutzt.",
        alle="Alle Textkanäle synchronisieren.",
        limit="Maximale Nachrichten pro Kanal. Leer lassen für 5000.",
    )
    async def messagesync(
        self,
        interaction: discord.Interaction,
        kanal: Optional[discord.TextChannel] = None,
        alle: bool = False,
        limit: Optional[int] = None,
    ) -> None:
        if not interaction.guild:
            await interaction.response.send_message(
                "Dieser Command funktioniert nur auf einem Server.",
                ephemeral=True,
            )
            return

        if interaction.guild.id in self._running_guilds:
            await interaction.response.send_message(
                "Für diesen Server läuft bereits ein Message-Sync.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        per_channel_limit = (
            max(1, min(limit, self.MAX_LIMIT_PER_CHANNEL))
            if limit
            else self.DEFAULT_LIMIT_PER_CHANNEL
        )
        channels: list[discord.TextChannel]
        if alle:
            me = interaction.guild.me
            if me is None and self.bot.user is not None:
                me = interaction.guild.get_member(self.bot.user.id)
            channels = [
                channel
                for channel in interaction.guild.text_channels
                if (
                    me is not None
                    and channel.permissions_for(me).read_messages
                    and channel.permissions_for(me).read_message_history
                )
            ]
        else:
            selected = kanal or interaction.channel
            if not isinstance(selected, discord.TextChannel):
                await interaction.followup.send(
                    "Bitte wähle einen Textkanal aus.",
                    ephemeral=True,
                )
                return
            channels = [selected]
        if not channels:
            await interaction.followup.send(
                "Keine lesbaren Textkanäle gefunden.",
                ephemeral=True,
            )
            return

        self._running_guilds.add(interaction.guild.id)
        await interaction.followup.send(
            f"Message-Sync gestartet: {len(channels)} Kanal/Kanäle, maximal {per_channel_limit} Nachrichten pro Kanal.",
            ephemeral=True,
        )
        asyncio.create_task(self._run_sync(interaction, channels, per_channel_limit))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageSyncCog(bot))
