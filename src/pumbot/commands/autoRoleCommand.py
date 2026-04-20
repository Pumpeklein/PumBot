from __future__ import annotations

from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger

AUTOROLE_STAFF_ROLES = {
    "Admin",
    "Team",
    "Twitch Moderator",
    "Discord Moderator",
    "Twitch Moderation",
    "Discord Moderation",
}
AUTOROLE_CONFIG_KEY = "autorole_ids"


def is_autorole_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if member.guild_permissions.manage_roles:
        return True
    return any(r.name in AUTOROLE_STAFF_ROLES for r in member.roles)


class AutoRoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api

    autorole_group = app_commands.Group(
        name="autorole",
        description="Automatische Rollen für neue User verwalten.",
    )

    async def _get_role_ids(self, guild_id: int) -> List[int]:
        raw = await self.api.get_config(str(guild_id), AUTOROLE_CONFIG_KEY)
        if not raw:
            return []

        role_ids: List[int] = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                role_ids.append(int(part))
        return role_ids

    async def _set_role_ids(self, guild_id: int, role_ids: List[int]) -> None:
        payload = ",".join(str(role_id) for role_id in sorted(set(role_ids)))
        await self.api.set_config(str(guild_id), AUTOROLE_CONFIG_KEY, payload)

    def _manageable_roles(
        self, guild: discord.Guild, role_ids: List[int]
    ) -> tuple[List[discord.Role], List[int]]:
        me = guild.me
        valid_roles: List[discord.Role] = []
        skipped_ids: List[int] = []

        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is None or role == guild.default_role:
                skipped_ids.append(role_id)
                continue
            if role.managed:
                skipped_ids.append(role_id)
                continue
            if me is None or role >= me.top_role:
                skipped_ids.append(role_id)
                continue
            valid_roles.append(role)

        return valid_roles, skipped_ids

    @autorole_group.command(name="add", description="Fügt eine Auto-Rolle hinzu.")
    @app_commands.describe(rolle="Rolle, die neue User automatisch erhalten sollen")
    async def autorole_add(
        self, interaction: discord.Interaction, rolle: discord.Role
    ) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_autorole_staff(user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.",
                ephemeral=True,
            )
            return

        me = guild.me
        if rolle == guild.default_role:
            await interaction.response.send_message(
                "Die `@everyone` Rolle kann nicht als Auto-Rolle gesetzt werden.",
                ephemeral=True,
            )
            return
        if rolle.managed:
            await interaction.response.send_message(
                "Verwaltete Rollen können nicht als Auto-Rolle gesetzt werden.",
                ephemeral=True,
            )
            return
        if me is None or rolle >= me.top_role:
            await interaction.response.send_message(
                "Ich kann diese Rolle nicht vergeben, weil sie über meiner höchsten Rolle liegt.",
                ephemeral=True,
            )
            return

        role_ids = await self._get_role_ids(guild.id)
        if rolle.id in role_ids:
            await interaction.response.send_message(
                f"{rolle.mention} ist bereits als Auto-Rolle eingetragen.",
                ephemeral=True,
            )
            return

        role_ids.append(rolle.id)
        await self._set_role_ids(guild.id, role_ids)
        await interaction.response.send_message(
            f"{rolle.mention} wurde als Auto-Rolle hinzugefügt.",
            ephemeral=True,
        )

    @autorole_group.command(name="remove", description="Entfernt eine Auto-Rolle.")
    @app_commands.describe(rolle="Rolle, die nicht mehr automatisch vergeben werden soll")
    async def autorole_remove(
        self, interaction: discord.Interaction, rolle: discord.Role
    ) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_autorole_staff(user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.",
                ephemeral=True,
            )
            return

        role_ids = await self._get_role_ids(guild.id)
        if rolle.id not in role_ids:
            await interaction.response.send_message(
                f"{rolle.mention} ist aktuell keine Auto-Rolle.",
                ephemeral=True,
            )
            return

        updated = [role_id for role_id in role_ids if role_id != rolle.id]
        await self._set_role_ids(guild.id, updated)
        await interaction.response.send_message(
            f"{rolle.mention} wurde aus den Auto-Rollen entfernt.",
            ephemeral=True,
        )

    @autorole_group.command(name="show", description="Zeigt alle gesetzten Auto-Rollen.")
    async def autorole_show(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        role_ids = await self._get_role_ids(guild.id)
        if not role_ids:
            await interaction.response.send_message(
                "Aktuell sind keine Auto-Rollen gesetzt.",
                ephemeral=True,
            )
            return

        roles = []
        missing = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is None:
                missing.append(role_id)
            else:
                roles.append(role.mention)

        lines = []
        if roles:
            lines.append("Aktive Auto-Rollen:")
            lines.extend(f"- {role}" for role in roles)
        if missing:
            lines.append("")
            lines.append("Nicht mehr vorhandene Rollen:")
            lines.extend(f"- `{role_id}`" for role_id in missing)

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @autorole_group.command(name="clear", description="Entfernt alle Auto-Rollen.")
    async def autorole_clear(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_autorole_staff(user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.",
                ephemeral=True,
            )
            return

        await self._set_role_ids(guild.id, [])
        await interaction.response.send_message(
            "Alle Auto-Rollen wurden entfernt.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        if guild is None or member.bot:
            return

        try:
            role_ids = await self._get_role_ids(guild.id)
            if not role_ids:
                return

            roles, skipped_ids = self._manageable_roles(guild, role_ids)
            if not roles:
                return

            await member.add_roles(*roles, reason="Automatische Join-Rollen")

            if skipped_ids:
                logger.warning(
                    "AutoRole: Einige Rollen konnten nicht vergeben werden in Guild %s: %s",
                    guild.id,
                    ", ".join(str(role_id) for role_id in skipped_ids),
                )
        except discord.Forbidden:
            logger.warning(
                "AutoRole: Fehlende Berechtigungen zum Vergeben von Rollen in Guild %s",
                guild.id,
            )
        except discord.HTTPException as e:
            logger.exception("AutoRole HTTPException beim Join: %r", e)
        except Exception:
            logger.exception("AutoRole on_member_join error")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoRoleCog(bot))
