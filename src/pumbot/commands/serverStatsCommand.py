from __future__ import annotations

from typing import Dict, Any, Optional

import discord
from discord.ext import commands
from discord import app_commands

from src.pumbot import config
from src.pumbot.bot import logger


STAT_DEFINITIONS: Dict[str, str] = {
    "all": "All Members",
    "members": "Members",
    "bots": "Bots",
    "channels": "Channels",
    "roles": "Roles",
}


class ServerStatsCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api

    # Slash-Command-Gruppe
    serverstats = app_commands.Group(
        name="serverstats",
        description="Verwalte die Server-Statistik-Kanaele.",
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

    async def _update_guild_stats(self, guild: discord.Guild) -> None:
        """Aktualisiert alle konfigurierten Stat-Channels fuer diese Guild."""
        try:
            cfg = await self._get_guild_config(guild.id)
            stats = self._get_stats(cfg)
            if not stats:
                return

            all_members = guild.member_count
            members = sum(1 for m in guild.members if not m.bot)
            bots = sum(1 for m in guild.members if m.bot)
            channels_count = len(guild.channels)
            roles_count = len(guild.roles)

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
                channel = guild.get_channel(int(channel_id_str))
                if channel is None:
                    continue

                label = STAT_DEFINITIONS.get(stat_key)
                value = values.get(stat_key)
                if label is None or value is None:
                    continue

                new_name = f"{label}: {value}"

                if channel.name != new_name:
                    await channel.edit(name=new_name, reason="Server-Stat-Update")

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
                "Dieser Bot ist fuer diesen Server nicht konfiguriert.",
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
        name="add", description="Fuegt einen zusaetzlichen Stat-Channel hinzu."
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(stat_type="Welche Statistik soll hinzugefuegt werden?")
    @app_commands.choices(
        stat_type=[
            app_commands.Choice(name="All Members", value="all"),
            app_commands.Choice(name="Members", value="members"),
            app_commands.Choice(name="Bots", value="bots"),
            app_commands.Choice(name="Channels", value="channels"),
            app_commands.Choice(name="Roles", value="roles"),
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
            f"Stat `{stat_key}` wurde hinzugefuegt.",
            ephemeral=True,
        )

    @serverstats.command(name="remove", description="Entfernt einen Stat-Channel.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        stat_key="Schluessel der Statistik (z. B. all, members, bots, channels, roles)"
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
        await self._update_guild_stats(member.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self._update_guild_stats(member.guild)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        await self._update_guild_stats(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        await self._update_guild_stats(channel.guild)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self._update_guild_stats(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self._update_guild_stats(role.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerStatsCog(bot))
