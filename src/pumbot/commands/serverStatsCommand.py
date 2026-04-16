from __future__ import annotations

import asyncio
from typing import Dict, Any, Optional

import discord
from discord.ext import commands, tasks
from discord import app_commands

from src.pumbot import config
from src.pumbot.bot import logger


STAT_DEFINITIONS: Dict[str, str] = {
    "all": "Alle Mitglieder",
    "members": "Mitglieder",
    "bots": "Bots",
    "channels": "Kanäle",
    "roles": "Rollen",
}


class ServerStatsCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self._update_lock = asyncio.Lock()
        self._pending_task: Optional[asyncio.Task] = None
        self._stats_loop.start()

    async def cog_unload(self) -> None:
        self._stats_loop.cancel()
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()

    @tasks.loop(minutes=5)
    async def _stats_loop(self) -> None:
        try:
            guild = self.bot.get_guild(config.GUILD_ID)
            if guild:
                await self._update_guild_stats(guild)
        except Exception:
            logger.exception("Server-Stats Loop: Fehler")

    @_stats_loop.before_loop
    async def _before_stats_loop(self) -> None:
        await self.bot.wait_until_ready()
        logger.info("Server-Stats: Bot ready.")

    def _schedule_update(self) -> None:
        """Debounce: plant ein Update in 5 s, vorheriges wird verworfen."""
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()
        self._pending_task = self.bot.loop.create_task(self._debounced_update())

    async def _debounced_update(self) -> None:
        try:
            await asyncio.sleep(5)
            guild = self.bot.get_guild(config.GUILD_ID)
            if guild:
                await self._update_guild_stats(guild, use_api=False)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Server-Stats: Fehler im debounced Update")

    # Slash-Command-Gruppe
    serverstats = app_commands.Group(
        name="serverstats",
        description="Verwalte die Server-Statistik-Kanäle.",
    )

    async def _get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        data = await self.api.get_server_stats(str(guild_id))
        if data is None:
            return {}
        return data

    async def _set_guild_config(self, guild_id: int, guild_config: Dict[str, Any]) -> None:
        await self.api.set_server_stats(str(guild_id), guild_config)

    def _get_stats(self, cfg: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """Extract stat channel IDs from the flat config."""
        return {k: cfg[k] for k in STAT_DEFINITIONS if k in cfg}

    async def _update_guild_stats(self, guild: discord.Guild, use_api: bool = True) -> None:
        """Aktualisiert alle konfigurierten Stat-Channels für diese Guild."""
        if self._update_lock.locked():
            return
        async with self._update_lock:
            await self._run_stat_update(guild, use_api)

    async def _run_stat_update(self, guild: discord.Guild, use_api: bool = True) -> None:
        try:
            cached_guild = self.bot.get_guild(guild.id)
            if not cached_guild:
                logger.warning("Server-Stats: Guild %s nicht im Cache.", guild.id)
                return

            cfg = await self._get_guild_config(cached_guild.id)
            stats = self._get_stats(cfg)
            if not stats:
                return

            if use_api:
                # Frische Daten von Discord holen (für Loop/Start)
                try:
                    channels = await cached_guild.fetch_channels()
                    channels_count = len(channels)
                except Exception:
                    channels_count = len(cached_guild.channels)
                try:
                    roles = await cached_guild.fetch_roles()
                    roles_count = len(roles)
                except Exception:
                    roles_count = len(cached_guild.roles)
            else:
                # Cache nutzen (bei Events ist der Cache bereits aktualisiert)
                channels_count = len(cached_guild.channels)
                roles_count = len(cached_guild.roles)

            all_members = cached_guild.member_count or 0
            members = sum(1 for m in cached_guild.members if not m.bot)
            bots = sum(1 for m in cached_guild.members if m.bot)

            values = {
                "all": all_members,
                "members": members,
                "bots": bots,
                "channels": channels_count,
                "roles": roles_count,
            }

            for stat_key, channel_id_str in stats.items():
                if channel_id_str is None:
                    continue
                channel = cached_guild.get_channel(int(channel_id_str))
                if channel is None:
                    continue

                label = STAT_DEFINITIONS.get(stat_key)
                value = values.get(stat_key)
                if label is None or value is None:
                    continue

                new_name = f"{label}: {value}"
                old_name = channel.name

                if old_name != new_name:
                    try:
                        await channel.edit(name=new_name, reason="Server-Stat-Update")
                        logger.info("Server-Stats: %s -> %s", old_name, new_name)
                    except discord.HTTPException as e:
                        logger.warning("Server-Stats: Konnte %s nicht umbenennen: %s", stat_key, e)

        except Exception:
            logger.exception("Fehler beim Aktualisieren der Server-Statistiken")

    async def _create_stat_channel(
        self,
        guild: discord.Guild,
        category: discord.CategoryChannel,
        stat_key: str,
    ) -> discord.VoiceChannel:
        label = STAT_DEFINITIONS[stat_key]
        channel = await guild.create_voice_channel(
            name=f"{label}: 0",
            category=category,
            reason="Server-Stats eingerichtet",
        )
        return channel

    @serverstats.command(
        name="setup", description="Richtet die Server-Stats in einer Kategorie ein."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def serverstats_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
    ):
        """Basis-Setup: Kategorie speichern und Default-Stats erstellen."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if guild.id != config.GUILD_ID:
            await interaction.response.send_message(
                "Dieser Bot ist für diesen Server nicht konfiguriert.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        cfg = await self._get_guild_config(guild.id)
        cfg["category_id"] = str(category.id)

        default_stats = ["all", "members", "bots"]
        for stat_key in default_stats:
            if stat_key in cfg:
                continue
            channel = await self._create_stat_channel(guild, category, stat_key)
            cfg[stat_key] = str(channel.id)

        await self._set_guild_config(guild.id, cfg)
        await self._update_guild_stats(guild)

        active = [k for k in STAT_DEFINITIONS if k in cfg]
        await interaction.followup.send(
            f"Server-Stats in der Kategorie `{category.name}` eingerichtet.\n"
            f"Aktive Stats: {', '.join(active)}",
            ephemeral=True,
        )

    @serverstats.command(
        name="add", description="Fügt einen zusätzlichen Stat-Channel hinzu."
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(stat_type="Welche Statistik soll hinzugefügt werden?")
    @app_commands.choices(
        stat_type=[
            app_commands.Choice(name="Alle Mitglieder", value="all"),
            app_commands.Choice(name="Mitglieder", value="members"),
            app_commands.Choice(name="Bots", value="bots"),
            app_commands.Choice(name="Kanäle", value="channels"),
            app_commands.Choice(name="Rollen", value="roles"),
        ]
    )
    async def serverstats_add(
        self,
        interaction: discord.Interaction,
        stat_type: app_commands.Choice[str],
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        stat_key = stat_type.value
        cfg = await self._get_guild_config(guild.id)
        category_id = cfg.get("category_id")

        if category_id is None:
            await interaction.response.send_message(
                "Es wurde noch keine Kategorie gesetzt. Nutze zuerst `/serverstats setup`.",
                ephemeral=True,
            )
            return

        if stat_key in cfg:
            await interaction.response.send_message(
                "Diese Statistik ist bereits eingerichtet.",
                ephemeral=True,
            )
            return

        category = guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "Die gespeicherte Kategorie existiert nicht mehr.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = await self._create_stat_channel(guild, category, stat_key)
        cfg[stat_key] = str(channel.id)
        await self._set_guild_config(guild.id, cfg)

        await self._update_guild_stats(guild)

        await interaction.followup.send(
            f"Stat `{stat_key}` wurde hinzugefügt.",
            ephemeral=True,
        )

    @serverstats.command(name="remove", description="Entfernt einen Stat-Channel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        stat_key="Schlüssel der Statistik (z. B. all, members, bots, channels, roles)"
    )
    async def serverstats_remove(
        self,
        interaction: discord.Interaction,
        stat_key: str,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        stat_key = stat_key.lower()
        cfg = await self._get_guild_config(guild.id)

        if stat_key not in STAT_DEFINITIONS or stat_key not in cfg:
            await interaction.response.send_message(
                "Diese Statistik ist nicht eingerichtet.",
                ephemeral=True,
            )
            return

        channel_id_str = cfg.pop(stat_key)
        channel = guild.get_channel(int(channel_id_str))
        if isinstance(channel, discord.VoiceChannel):
            await channel.delete(reason="Server-Stat entfernt")

        await self._set_guild_config(guild.id, cfg)

        await interaction.response.send_message(
            f"Stat `{stat_key}` wurde entfernt.",
            ephemeral=True,
        )

    @serverstats.command(
        name="list", description="Zeigt die aktuelle Server-Stats-Konfiguration an."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def serverstats_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        cfg = await self._get_guild_config(guild.id)
        category_id = cfg.get("category_id")
        stats = self._get_stats(cfg)

        if not category_id and not stats:
            await interaction.response.send_message(
                "Es ist noch keine Server-Stats-Konfiguration vorhanden.",
                ephemeral=True,
            )
            return

        lines = []
        if category_id:
            category = guild.get_channel(int(category_id))
            category_name = (
                category.name
                if isinstance(category, discord.CategoryChannel)
                else "Unbekannt"
            )
            lines.append(f"Kategorie: `{category_name}` (ID: {category_id})")

        if stats:
            lines.append("Aktive Stats:")
            for key, ch_id in stats.items():
                if ch_id is None:
                    continue
                ch = guild.get_channel(int(ch_id))
                ch_name = (
                    ch.name
                    if isinstance(ch, discord.VoiceChannel)
                    else "Unbekannter Kanal"
                )
                lines.append(f"- `{key}` -> {ch_name} (ID: {ch_id})")
        else:
            lines.append("Keine Stats eingerichtet.")

        await interaction.response.send_message(
            "\n".join(lines),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id == config.GUILD_ID:
            self._schedule_update()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id == config.GUILD_ID:
            self._schedule_update()

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        if channel.guild.id == config.GUILD_ID:
            self._schedule_update()

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if channel.guild.id == config.GUILD_ID:
            self._schedule_update()

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        if role.guild.id == config.GUILD_ID:
            self._schedule_update()

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        if role.guild.id == config.GUILD_ID:
            self._schedule_update()


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStatsCog(bot))
