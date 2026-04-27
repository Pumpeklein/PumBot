from __future__ import annotations

from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot import config
from src.pumbot.bot import logger

WELCOME_CHANNEL_CONFIG_KEY = "welcome_channel_id"
WELCOME_STAFF_ROLES = {"Admin", "Team", "Discord Moderator", "Discord Moderation"}


def is_welcome_staff(member: discord.Member) -> bool:
    try:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        return any(role.name in WELCOME_STAFF_ROLES for role in member.roles)
    except Exception:
        logger.exception("is_welcome_staff error")
        return False


def _find_project_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "assets").is_dir():
            return p
    return start


PROJECT_ROOT = _find_project_root(Path(__file__).resolve())
WELCOME_BANNER_PATH = PROJECT_ROOT / "assets" / "welcome_banner.gif"


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    welcome = app_commands.Group(
        name="welcome",
        description="Verwalte und teste die Willkommensnachrichten.",
    )

    async def _build_welcome_embed(self, member: discord.Member) -> discord.Embed:
        try:
            guild = member.guild

            embed = discord.Embed(
                title=f"Willkommen auf {guild.name}!",
                description=(
                    f"{member.mention}, schön, dass du da bist! 🎉\n\n"
                    "Schau dir bitte unsere Regeln an und hol dir deine Rollen.\n"
                    "Wir wünschen dir ganz viel Spaß auf dem Server!"
                ),
                color=discord.Color.blurple(),
            )

            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Du bist Mitglied #{guild.member_count}")

            return embed
        except Exception:
            logger.exception("Fehler beim Erstellen des Welcome-Embeds")
            return discord.Embed(
                description=f"{member.mention}, willkommen auf dem Server! 🎉",
                color=discord.Color.red(),
            )

    async def _get_welcome_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.abc.Messageable]:
        channel_id = config.WELCOME_CHANNEL_ID
        try:
            configured_channel_id = await self.bot.api.get_config(
                str(guild.id), WELCOME_CHANNEL_CONFIG_KEY
            )
            if configured_channel_id:
                channel_id = int(configured_channel_id)
        except Exception:
            logger.exception("Welcome-Channel-Konfiguration konnte nicht geladen werden")

        channel = guild.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await guild.fetch_channel(channel_id)
        except Exception:
            logger.exception(
                "Welcome-Channel konnte nicht geladen werden (ID: %s)",
                channel_id,
            )
            return None

    async def _send_welcome_message(self, member: discord.Member) -> None:
        try:
            guild = member.guild

            if guild.id != config.GUILD_ID:
                return

            channel = await self._get_welcome_channel(guild)
            if channel is None:
                return

            embed = await self._build_welcome_embed(member)

            if WELCOME_BANNER_PATH.is_file():
                file = discord.File(WELCOME_BANNER_PATH, filename="welcome_banner.gif")
                embed.set_image(url="attachment://welcome_banner.gif")
                await channel.send(content=member.mention, embed=embed, file=file)
            else:
                await channel.send(content=member.mention, embed=embed)

        except Exception:
            logger.exception("Fehler beim Senden der Willkommensnachricht")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        await self._send_welcome_message(member)

    @welcome.command(
        name="test",
        description="Sendet die Willkommensnachricht testweise für ein Mitglied.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        member="Mitglied, für das die Willkommensnachricht getestet werden soll (optional).",
    )
    async def welcome_test(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        target: Optional[discord.Member] = member
        if target is None:
            target = guild.get_member(interaction.user.id)
            if target is None:
                try:
                    target = await guild.fetch_member(interaction.user.id)
                except Exception:
                    logger.exception(
                        "Konnte Member nicht laden (ID: %s)", interaction.user.id
                    )
                    await interaction.followup.send(
                        "Konnte das Mitglied nicht laden.", ephemeral=True
                    )
                    return

        await self._send_welcome_message(target)

        await interaction.followup.send(
            f"Willkommensnachricht für {target.mention} wurde im Welcome-Channel gesendet.",
            ephemeral=True,
        )

    @welcome_test.error
    async def welcome_test_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "Dir fehlen Rechte dafür (Administrator)."
        else:
            msg = "Interner Fehler beim Command."
            logger.exception("Fehler in /welcome test", exc_info=error)

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    @welcome.command(
        name="set_channel",
        description="Setzt den Channel für Willkommensnachrichten.",
    )
    @app_commands.describe(channel="Textkanal für Willkommensnachrichten")
    async def welcome_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member) or not is_welcome_staff(
            interaction.user
        ):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.",
                ephemeral=True,
            )
            return

        try:
            await self.bot.api.set_config(
                str(interaction.guild.id),
                WELCOME_CHANNEL_CONFIG_KEY,
                str(channel.id),
            )
        except Exception:
            logger.exception("Welcome-Channel konnte nicht gespeichert werden")
            await interaction.response.send_message(
                "Der Welcome-Channel konnte nicht gespeichert werden.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Willkommens-Channel wurde auf {channel.mention} gesetzt.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
