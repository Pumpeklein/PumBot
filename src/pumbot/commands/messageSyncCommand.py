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
        channel,
        limit: int | None,
        *,
        insert_only: bool = False,
    ) -> tuple[int, int]:
        batch: list[dict] = []
        synced = 0
        skipped = 0
        async for message in channel.history(limit=limit, oldest_first=True):
            if message.author.bot:
                continue
            batch.append(self.bot.message_payload(message))
            if len(batch) >= self.BATCH_SIZE:
                result = await self.bot.api.upsert_guild_messages(
                    guild_id, batch, insert_only=insert_only
                )
                synced += int((result or {}).get("synced") or 0)
                skipped += int((result or {}).get("skipped") or 0)
                batch = []
                await asyncio.sleep(0)
        if batch:
            result = await self.bot.api.upsert_guild_messages(
                guild_id, batch, insert_only=insert_only
            )
            synced += int((result or {}).get("synced") or 0)
            skipped += int((result or {}).get("skipped") or 0)
        return synced, skipped

    @staticmethod
    def _channel_label(channel) -> str:
        name = getattr(channel, "name", None)
        return f"#{name}" if name else str(getattr(channel, "id", "unbekannt"))

    @staticmethod
    def _is_readable_message_channel(channel, member: discord.Member | None) -> bool:
        if member is None or channel is None or not hasattr(channel, "history"):
            return False
        permissions_for = getattr(channel, "permissions_for", None)
        if permissions_for is None:
            return False
        perms = permissions_for(member)
        can_view = getattr(perms, "view_channel", False) or getattr(
            perms, "read_messages", False
        )
        return bool(can_view and getattr(perms, "read_message_history", False))

    async def _iter_archived_threads(self, parent) -> list[discord.Thread]:
        threads: list[discord.Thread] = []
        archived_threads = getattr(parent, "archived_threads", None)
        if archived_threads is None:
            return threads

        async def collect(**kwargs) -> None:
            with contextlib.suppress(discord.Forbidden, discord.HTTPException, TypeError):
                async for thread in archived_threads(limit=None, **kwargs):
                    threads.append(thread)

        await collect()
        await collect(private=True)
        return threads

    async def _all_message_channels(self, guild: discord.Guild) -> list:
        me = guild.me
        if me is None and self.bot.user is not None:
            me = guild.get_member(self.bot.user.id)

        channels: list = []
        seen: set[int] = set()

        def add(channel) -> None:
            channel_id = getattr(channel, "id", None)
            if channel_id is None or channel_id in seen:
                return
            if self._is_readable_message_channel(channel, me):
                seen.add(channel_id)
                channels.append(channel)

        for channel in guild.text_channels:
            add(channel)
        for channel in getattr(guild, "voice_channels", []):
            add(channel)
        for channel in getattr(guild, "stage_channels", []):
            add(channel)
        for thread in getattr(guild, "threads", []):
            add(thread)

        archive_parents = list(guild.text_channels) + list(
            getattr(guild, "forum_channels", [])
        )
        for parent in archive_parents:
            if not self._is_readable_message_channel(parent, me):
                continue
            for thread in await self._iter_archived_threads(parent):
                add(thread)

        return channels

    async def _run_sync(
        self,
        interaction: discord.Interaction,
        channels: list,
        limit: int | None,
        *,
        insert_only: bool = False,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return

        guild_id = str(guild.id)
        synced = 0
        skipped = 0
        failed: list[str] = []
        try:
            for channel in channels:
                try:
                    channel_synced, channel_skipped = await self._sync_channel(
                        guild_id, channel, limit, insert_only=insert_only
                    )
                    synced += channel_synced
                    skipped += channel_skipped
                except discord.Forbidden:
                    failed.append(self._channel_label(channel))
                except discord.HTTPException:
                    logger.exception(
                        "Message-Sync fuer %s fehlgeschlagen",
                        self._channel_label(channel),
                    )
                    failed.append(self._channel_label(channel))
                except Exception:
                    logger.exception(
                        "Message-Sync fuer %s unerwartet fehlgeschlagen",
                        self._channel_label(channel),
                    )
                    failed.append(self._channel_label(channel))

            skipped_text = (
                f" {skipped} vorhandene Eintraege uebersprungen." if skipped else ""
            )
            suffix = f" Fehlgeschlagen: {', '.join(failed[:5])}" if failed else ""
            with contextlib.suppress(Exception):
                await interaction.followup.send(
                    f"Message-Sync fertig: {synced} neue Nachrichten aus {len(channels)} Kanal/Kanaelen gespeichert."
                    f"{skipped_text}{suffix}",
                    ephemeral=True,
                )
        except Exception:
            logger.exception("Message-Sync Hintergrundtask fuer Guild %s abgebrochen", guild_id)
            with contextlib.suppress(Exception):
                await interaction.followup.send(
                    "Message-Sync ist abgebrochen. Details stehen im Bot-Log.",
                    ephemeral=True,
                )
        finally:
            self._running_guilds.discard(guild.id)

    @app_commands.command(
        name="messagesync",
        description="Importiert Nachrichten aus einem Kanal oder allen lesbaren Chats ins Dashboard.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        kanal="Optionaler Textkanal. Ohne Angabe wird der aktuelle Kanal genutzt.",
        channel_id="Optional: Kanal-/Thread-ID fuer Voice-Chats oder Threads.",
        alle="Alle Text-, Voice-Chat- und Thread-Chats synchronisieren.",
        limit="Maximale Nachrichten pro Kanal. Leer lassen fuer 5000.",
    )
    async def messagesync(
        self,
        interaction: discord.Interaction,
        kanal: Optional[discord.TextChannel] = None,
        channel_id: Optional[str] = None,
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
                "Fuer diesen Server laeuft bereits ein Message-Sync.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        per_channel_limit = (
            max(1, min(limit, self.MAX_LIMIT_PER_CHANNEL))
            if limit
            else self.DEFAULT_LIMIT_PER_CHANNEL
        )
        channels: list
        insert_only = False
        if alle:
            channels = await self._all_message_channels(interaction.guild)
            insert_only = True
        else:
            selected = None
            if channel_id:
                try:
                    channel_id_int = int(channel_id)
                    get_channel_or_thread = getattr(
                        interaction.guild, "get_channel_or_thread", None
                    )
                    selected = (
                        get_channel_or_thread(channel_id_int)
                        if get_channel_or_thread
                        else interaction.guild.get_channel(channel_id_int)
                    )
                    if selected is None:
                        selected = await interaction.guild.fetch_channel(channel_id_int)
                except (
                    ValueError,
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    selected = None
            selected = selected or kanal or interaction.channel
            me = interaction.guild.me
            if me is None and self.bot.user is not None:
                me = interaction.guild.get_member(self.bot.user.id)
            if not self._is_readable_message_channel(selected, me):
                await interaction.followup.send(
                    "Bitte waehle einen lesbaren Text-, Voice-Chat- oder Thread-Kanal aus.",
                    ephemeral=True,
                )
                return
            channels = [selected]

        if not channels:
            await interaction.followup.send(
                "Keine lesbaren Chats gefunden.",
                ephemeral=True,
            )
            return

        self._running_guilds.add(interaction.guild.id)
        await interaction.followup.send(
            f"Message-Sync gestartet: {len(channels)} Kanal/Kanaele, maximal {per_channel_limit} Nachrichten pro Kanal.",
            ephemeral=True,
        )
        asyncio.create_task(
            self._run_sync(
                interaction,
                channels,
                per_channel_limit,
                insert_only=insert_only,
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MessageSyncCog(bot))
