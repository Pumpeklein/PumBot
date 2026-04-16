from __future__ import annotations

from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger
from src.pumbot.utils.datetime_format import format_berlin_datetime

ALLOWED_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}


def is_allowed(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.name in ALLOWED_ROLES for role in member.roles)


def format_birthday(day: int, month: int, year: int | None) -> str:
    try:
        if year is None:
            return f"{day:02d}.{month:02d}"
        if year < 100:
            return f"{day:02d}.{month:02d}.{year:02d}"
        return f"{day:02d}.{month:02d}.{year:04d}"
    except Exception:
        logger.exception("format_birthday error")
        return f"{day:02d}.{month:02d}"


def format_dt(dt) -> str:
    try:
        return format_berlin_datetime(dt, fallback="Unbekannt")
    except Exception:
        logger.exception("format_dt error")
        return "Unbekannt"


class UserManagementCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api

    moderation_group = app_commands.Group(
        name="mod",
        description="Moderations-Commands (Warn, Timeout, Ban, Userinfo, etc.).",
    )

    @moderation_group.command(
        name="profile", description="Zeigt Infos über einen Nutzer."
    )
    @app_commands.describe(user="User (optional)")
    async def profile(
        self, interaction: discord.Interaction, user: Optional[discord.Member] = None
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        member = user or interaction.user
        guild = interaction.guild

        roles = [role.mention for role in member.roles if role != guild.default_role]
        roles_text = ", ".join(roles) if roles else "Keine Rollen"

        perms = [
            name.replace("_", " ") for name, value in member.guild_permissions if value
        ]
        perms_text = ", ".join(perms) if perms else "Keine besonderen Rechte"

        birthday_text = "Kein Geburtstag gespeichert"
        try:
            bday = await self.api.get_birthday(str(guild.id), str(member.id))
            if bday:
                day = bday.get("day")
                month = bday.get("month")
                year = bday.get("year")
                if day is not None and month is not None:
                    birthday_text = format_birthday(day, month, year)
        except Exception:
            logger.exception("profile get_birthday error")

        embed = discord.Embed(
            title=f"Benutzerinfo - {member}",
            color=(
                member.color
                if isinstance(member, discord.Member)
                else discord.Color.blurple()
            ),
        )

        try:
            embed.set_thumbnail(url=member.display_avatar.url)
        except Exception:
            pass

        embed.add_field(
            name="Namen",
            value=(
                f"**Benutzername:** {member.name}\n"
                f"**Anzeigename:** {member.display_name}\n"
                f"**Nickname:** {member.nick if member.nick else 'Kein Nickname'}"
            ),
            inline=False,
        )

        embed.add_field(
            name="IDs & Daten",
            value=(
                f"**User ID:** `{member.id}`\n"
                f"**Account erstellt:** {format_dt(member.created_at)}\n"
                f"**Server beigetreten:** {format_dt(member.joined_at)}\n"
                f"**Join-Methode:** Nicht direkt über die Discord-API verfügbar"
            ),
            inline=False,
        )

        embed.add_field(name="Geburtstag", value=birthday_text, inline=False)
        embed.add_field(name="Rollen", value=roles_text, inline=False)
        embed.add_field(
            name="Rechte (Auszug)",
            value=perms_text[:1024] if perms_text else "Keine",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=False)

    @moderation_group.command(
        name="warn", description="Verwarnt einen Nutzer und speichert den Grund."
    )
    @app_commands.describe(user="User", grund="Grund (optional)")
    async def warn(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        grund: Optional[str] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "Du kannst dich nicht selbst verwarnen.", ephemeral=True
            )
            return

        if (
            user.top_role >= interaction.user.top_role
            and interaction.user != interaction.guild.owner
        ):
            await interaction.response.send_message(
                "Du kannst keinen User verwarnen, der gleich- oder höhergestellt ist als du.",
                ephemeral=True,
            )
            return

        reason_text = grund or "Kein Grund angegeben"

        try:
            await self.api.add_warning(
                str(interaction.guild.id),
                str(user.id),
                str(interaction.user.id),
                reason_text,
            )
        except Exception:
            logger.exception("warn add_warning error")
            await interaction.response.send_message(
                "Beim Speichern der Verwarnung ist ein Fehler aufgetreten.",
                ephemeral=True,
            )
            return

        try:
            warns = await self.api.get_warnings(
                str(interaction.guild.id), str(user.id)
            )
            count = len(warns)
        except Exception:
            logger.exception("warn get_warnings count error")
            count = "?"

        await interaction.response.send_message(
            f"{user.mention} wurde verwarnt. (Verwarnungen auf diesem Server: **{count}**)\nGrund: {reason_text}",
            ephemeral=False,
        )

        try:
            await user.send(
                f"Du wurdest auf **{interaction.guild.name}** verwarnt.\nGrund: {reason_text}"
            )
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            logger.exception("warn DM HTTPException")

    @moderation_group.command(
        name="warnings", description="Zeigt alle Verwarnungen eines Nutzers an."
    )
    @app_commands.describe(user="User")
    async def warnings(self, interaction: discord.Interaction, user: discord.Member):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        try:
            warns = await self.api.get_warnings(
                str(interaction.guild.id), str(user.id)
            )
        except Exception:
            logger.exception("warnings get_warnings error")
            await interaction.response.send_message(
                "Beim Abrufen der Verwarnungen ist ein Fehler aufgetreten.",
                ephemeral=True,
            )
            return

        if not warns:
            await interaction.response.send_message(
                f"{user.mention} hat bisher keine Verwarnungen.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Verwarnungen - {user}",
            color=discord.Color.orange(),
        )

        for idx, entry in enumerate(warns, start=1):
            mod_id = entry.get("moderator_id")
            mod_mention = f"<@{mod_id}>" if mod_id else "Unbekannt"
            reason = entry.get("reason", "Kein Grund angegeben")
            created_at = format_dt(entry.get("created_at"))
            warning_id = entry.get("id", "?")

            embed.add_field(
                name=f"Verwarnung #{idx} (ID: {warning_id})",
                value=f"**Moderator:** {mod_mention}\n**Zeit:** {created_at}\n**Grund:** {reason}",
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @moderation_group.command(
        name="clearwarnings",
        description="Löscht Verwarnungen eines Users (ohne Index: alle).",
    )
    @app_commands.describe(
        user="User", index="Index (1-basiert) einer einzelnen Verwarnung (optional)"
    )
    async def clearwarnings(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        index: Optional[int] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        if (
            user.top_role >= interaction.user.top_role
            and interaction.user != interaction.guild.owner
        ):
            await interaction.response.send_message(
                "Du kannst keine Verwarnungen von Usern löschen, die gleich- oder höhergestellt sind als du.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild.id)
        user_id = str(user.id)

        if index is not None:
            try:
                warns = await self.api.get_warnings(guild_id, user_id)
            except Exception:
                logger.exception("clearwarnings get_warnings error")
                await interaction.response.send_message(
                    "Beim Abrufen der Verwarnungen ist ein Fehler aufgetreten.",
                    ephemeral=True,
                )
                return

            if not warns or index < 1 or index > len(warns):
                count_now = len(warns) if warns else 0
                await interaction.response.send_message(
                    f"Ungültiger Index. {user.mention} hat **{count_now}** Verwarnung(en).",
                    ephemeral=True,
                )
                return

            warning_id = warns[index - 1].get("id")
            try:
                await self.api.remove_warning(guild_id, warning_id)
            except Exception:
                logger.exception("clearwarnings remove_warning error")
                await interaction.response.send_message(
                    "Beim Löschen der Verwarnung ist ein Fehler aufgetreten.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"Verwarnung #{index} von {user.mention} wurde gelöscht.",
                ephemeral=True,
            )
            return

        try:
            warns = await self.api.get_warnings(guild_id, user_id)
            count = len(warns) if warns else 0
        except Exception:
            logger.exception("clearwarnings get_warnings error")
            count = 0

        if count <= 0:
            await interaction.response.send_message(
                f"{user.mention} hat keine Verwarnungen, die gelöscht werden können.",
                ephemeral=True,
            )
            return

        try:
            await self.api.clear_warnings(guild_id, user_id)
        except Exception:
            logger.exception("clearwarnings clear_warnings error")
            await interaction.response.send_message(
                "Beim Löschen der Verwarnungen ist ein Fehler aufgetreten.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Alle Verwarnungen von {user.mention} wurden gelöscht. (Gelöscht: **{count}**)",
            ephemeral=True,
        )

    @moderation_group.command(name="ban", description="Bannt einen Nutzer vom Server.")
    @app_commands.describe(user="User", grund="Grund (optional)")
    async def ban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        grund: Optional[str] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "Du kannst dich nicht selbst bannen.", ephemeral=True
            )
            return

        if (
            user.top_role >= interaction.user.top_role
            and interaction.user != interaction.guild.owner
        ):
            await interaction.response.send_message(
                "Du kannst keinen User bannen, der gleich- oder höhergestellt ist als du.",
                ephemeral=True,
            )
            return

        reason_text = grund or "Kein Grund angegeben"

        try:
            await user.send(
                f"Du wurdest von **{interaction.guild.name}** gebannt.\nGrund: {reason_text}"
            )
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            logger.exception("ban DM HTTPException")

        try:
            await user.ban(reason=reason_text)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Ich habe keine Berechtigung, diesen User zu bannen.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            logger.exception("ban HTTPException: %r", e)
            await interaction.response.send_message(
                f"Beim Bannen ist ein Fehler aufgetreten: `{e}`", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"{user} wurde gebannt.\nGrund: {reason_text}", ephemeral=False
        )

    @moderation_group.command(
        name="timeout", description="Gibt einem Nutzer einen Timeout (in Minuten)."
    )
    @app_commands.describe(
        user="User", minuten="Dauer in Minuten", grund="Grund (optional)"
    )
    async def timeout(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        minuten: int,
        grund: Optional[str] = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_allowed(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        if minuten <= 0:
            await interaction.response.send_message(
                "Die Minuten müssen größer als 0 sein.", ephemeral=True
            )
            return

        if user.id == interaction.user.id:
            await interaction.response.send_message(
                "Du kannst dich nicht selbst timeouten.", ephemeral=True
            )
            return

        if (
            user.top_role >= interaction.user.top_role
            and interaction.user != interaction.guild.owner
        ):
            await interaction.response.send_message(
                "Du kannst keinen User timeouten, der gleich- oder höhergestellt ist als du.",
                ephemeral=True,
            )
            return

        me = interaction.guild.me
        if me and user.top_role >= me.top_role:
            await interaction.response.send_message(
                "Ich kann diesen User nicht timeouten (meine Rolle ist zu niedrig).",
                ephemeral=True,
            )
            return

        duration = timedelta(minutes=minuten)
        reason_text = grund or "Kein Grund angegeben"

        try:
            if hasattr(user, "timeout"):
                await user.timeout(duration, reason=reason_text)
            else:
                until = discord.utils.utcnow() + duration
                await user.edit(timed_out_until=until, reason=reason_text)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Ich habe keine Berechtigung, diesen User zu timeouten.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            logger.exception("timeout HTTPException: %r", e)
            await interaction.response.send_message(
                f"Beim Setzen des Timeouts ist ein Fehler aufgetreten: `{e}`",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"{user.mention} wurde für **{minuten}** Minuten in Timeout gesetzt.\nGrund: {reason_text}",
            ephemeral=False,
        )

        try:
            await user.send(
                f"Du wurdest auf **{interaction.guild.name}** für {minuten} Minuten in Timeout gesetzt.\nGrund: {reason_text}"
            )
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            logger.exception("timeout DM HTTPException")


async def setup(bot: commands.Bot):
    await bot.add_cog(UserManagementCog(bot))
