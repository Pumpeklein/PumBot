from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class ServerInfoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="serverinfo",
        description="Zeigt Informationen über den Server an.",
    )
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur in einem Server verwendet werden.",
                ephemeral=True,
            )
            return


        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id) if guild.owner_id else None
            except Exception:
                owner = None


        is_community = "COMMUNITY" in guild.features
        community_text = "Community ✅" if is_community else "Privat 🔒"

        member_count = guild.member_count or 0
        roles_count = max(0, len(guild.roles) - 1)  # -1 für @everyone
        text_channels_count = len(guild.text_channels)
        voice_channels_count = len(guild.voice_channels)


        team_count: str | int
        if guild.members:
            staff_ids: set[int] = set()
            for m in guild.members:
                if m.bot:
                    continue

                perms = m.guild_permissions
                if (
                    perms.administrator
                    or perms.manage_guild
                    or perms.manage_channels
                    or perms.manage_roles
                    or perms.ban_members
                    or perms.kick_members
                    or perms.mute_members
                    or perms.kick_members
                    or perms.moderate_members
                ):
                    staff_ids.add(m.id)

            team_count = len(staff_ids)
        else:
            team_count = "Nicht verfügbar"

        created = discord.utils.format_dt(guild.created_at, style="F")
        created_rel = discord.utils.format_dt(guild.created_at, style="R")

        embed = discord.Embed(
            title=f"Server Info — {guild.name}",
            description=community_text,
            color=discord.Color.blurple(),
        )


        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="📅 Erstellt am", value=f"{created}\n({created_rel})", inline=True)
        embed.add_field(name="👑 Owner", value=(owner.mention if owner else "Unbekannt"), inline=True)
        embed.add_field(name="🆔 Server ID", value=str(guild.id), inline=True)

        embed.add_field(name="👥 Member", value=str(member_count), inline=True)
        embed.add_field(name="🔖 Rollen", value=str(roles_count), inline=True)
        embed.add_field(name="🛡️ Teamler", value=str(team_count), inline=True)

        embed.add_field(name="💬 Textkanäle", value=str(text_channels_count), inline=True)
        embed.add_field(name="🔊 Sprachkanäle", value=str(voice_channels_count), inline=True)

        embed.set_footer(text="PumpBot | ServerInfo")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerInfoCog(bot))
