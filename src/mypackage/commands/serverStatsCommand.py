from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

import discord
from discord.ext import commands
from discord import app_commands

from src.mypackage import config
from src.mypackage.bot import logger

BASE_DIR = Path(__file__).resolve().parent.parent
STATS_FILE = BASE_DIR / "database" / "server_stats.json"


STAT_DEFINITIONS: Dict[str, str] = {
    "all": "All Members",
    "members": "Members",
    "bots": "Bots",
    "channels": "Channels",
    "roles": "Roles",
}


def _load_data() -> Dict[str, Any]:
    try:
        if not STATS_FILE.exists():
            return {"guilds": {}}
        with STATS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Fehler beim Laden der Server-Stats-Datei")
        return {"guilds": {}}


def _save_data(data: Dict[str, Any]) -> None:
    """Speichert die komplette Server-Stats-Konfiguration in JSON."""
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        logger.exception("Fehler beim Speichern der Server-Stats-Datei")


class ServerStatsCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Slash-Command-Gruppe
    serverstats = app_commands.Group(
        name="serverstats",
        description="Verwalte die Server-Statistik-Kanäle.",
    )

    def _get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        data = _load_data()
        return data.get("guilds", {}).get(str(guild_id), {})

    def _set_guild_config(self, guild_id: int, guild_config: Dict[str, Any]) -> None:
        data = _load_data()
        guilds = data.setdefault("guilds", {})
        guilds[str(guild_id)] = guild_config
        _save_data(data)

    async def _update_guild_stats(self, guild: discord.Guild) -> None:
        """Aktualisiert alle konfigurierten Stat-Channels für diese Guild."""
        try:
            cfg = self._get_guild_config(guild.id)
            stats_cfg: Dict[str, int] = cfg.get("stats", {})
            if not stats_cfg:
                return

            all_members = guild.member_count
            members = sum(1 for m in guild.members if not m.bot)
            bots = sum(1 for m in guild.members if m.bot)
            channels = len(guild.channels)
            roles = len(guild.roles)

            values = {
                "all": all_members,
                "members": members,
                "bots": bots,
                "channels": channels,
                "roles": roles,
            }

            for stat_key, channel_id in stats_cfg.items():
                channel = guild.get_channel(channel_id)
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
                "Dieser Bot ist für diesen Server nicht konfiguriert.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        cfg = self._get_guild_config(guild.id)
        cfg["category_id"] = category.id
        cfg.setdefault("stats", {})

        default_stats = ["all", "members", "bots"]
        for stat_key in default_stats:
            if stat_key in cfg["stats"]:
                continue
            channel = await self._create_stat_channel(guild, category, stat_key)
            cfg["stats"][stat_key] = channel.id

        self._set_guild_config(guild.id, cfg)
        await self._update_guild_stats(guild)

        await interaction.followup.send(
            f"Server-Stats in der Kategorie `{category.name}` eingerichtet.\n"
            f"Aktive Stats: {', '.join(cfg['stats'].keys())}",
            ephemeral=True,
        )

    @serverstats.command(
        name="add", description="Fügt einen zusätzlichen Stat-Channel hinzu."
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(stat_type="Welche Statistik soll hinzugefügt werden?")
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
        cfg = self._get_guild_config(guild.id)
        category_id = cfg.get("category_id")

        if category_id is None:
            await interaction.response.send_message(
                "Es wurde noch keine Kategorie gesetzt. Nutze zuerst `/serverstats setup`.",
                ephemeral=True,
            )
            return

        stats_cfg: Dict[str, int] = cfg.setdefault("stats", {})
        if stat_key in stats_cfg:
            await interaction.response.send_message(
                "Diese Statistik ist bereits eingerichtet.",
                ephemeral=True,
            )
            return

        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message(
                "Die gespeicherte Kategorie existiert nicht mehr.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = await self._create_stat_channel(guild, category, stat_key)
        stats_cfg[stat_key] = channel.id
        self._set_guild_config(guild.id, cfg)

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
        cfg = self._get_guild_config(guild.id)
        stats_cfg: Dict[str, int] = cfg.get("stats", {})

        if stat_key not in stats_cfg:
            await interaction.response.send_message(
                "Diese Statistik ist nicht eingerichtet.",
                ephemeral=True,
            )
            return

        channel_id = stats_cfg.pop(stat_key)
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            await channel.delete(reason="Server-Stat entfernt")

        self._set_guild_config(guild.id, cfg)

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

        cfg = self._get_guild_config(guild.id)
        category_id = cfg.get("category_id")
        stats_cfg: Dict[str, int] = cfg.get("stats", {})

        if not category_id and not stats_cfg:
            await interaction.response.send_message(
                "Es ist noch keine Server-Stats-Konfiguration vorhanden.",
                ephemeral=True,
            )
            return

        lines = []
        if category_id:
            category = guild.get_channel(category_id)
            category_name = (
                category.name
                if isinstance(category, discord.CategoryChannel)
                else "Unbekannt"
            )
            lines.append(f"Kategorie: `{category_name}` (ID: {category_id})")

        if stats_cfg:
            lines.append("Aktive Stats:")
            for key, ch_id in stats_cfg.items():
                ch = guild.get_channel(ch_id)
                ch_name = (
                    ch.name
                    if isinstance(ch, discord.VoiceChannel)
                    else "Unbekannter Kanal"
                )
                lines.append(f"- `{key}` → {ch_name} (ID: {ch_id})")
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
