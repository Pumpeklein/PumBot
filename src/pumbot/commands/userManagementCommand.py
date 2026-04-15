from __future__ import annotations

import json
from pathlib import Path
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger

DATA_DIR = Path("data")
WARNINGS_FILE = DATA_DIR / "warnings.json"
BIRTHDAY_FILE = DATA_DIR / "birthdays.json"

ALLOWED_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}


def is_allowed(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.name in ALLOWED_ROLES for role in member.roles)


def load_warnings() -> dict:
    if not WARNINGS_FILE.exists():
        return {}
    try:
        with WARNINGS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning("warnings.json ist kaputt/leer -> starte mit {}")
        return {}
    except Exception:
        logger.exception("load_warnings error")
        return {}


def save_warnings(data: dict) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with WARNINGS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        logger.exception("save_warnings error")


def add_warning(
    guild_id: int, user_id: int, moderator_id: int, reason: str | None
) -> int:
    try:
        data = load_warnings()
        g_id = str(guild_id)
        u_id = str(user_id)

        data.setdefault(g_id, {})
        data[g_id].setdefault(u_id, [])

        entry = {
            "moderator_id": moderator_id,
            "reason": reason or "Kein Grund angegeben",
            "timestamp": discord.utils.utcnow().isoformat(),
        }
        data[g_id][u_id].append(entry)
        save_warnings(data)
        return len(data[g_id][u_id])
    except Exception:
        logger.exception("add_warning error")
        return 0


def get_warnings(guild_id: int, user_id: int) -> list[dict]:
    try:
        data = load_warnings()
        return data.get(str(guild_id), {}).get(str(user_id), []) or []
    except Exception:
        logger.exception("get_warnings error")
        return []


def clear_warnings_all(guild_id: int, user_id: int) -> int:
    try:
        data = load_warnings()
        g_id = str(guild_id)
        u_id = str(user_id)

        warns = data.get(g_id, {}).get(u_id, [])
        count = len(warns)

        if g_id in data and u_id in data[g_id]:
            del data[g_id][u_id]
            save_warnings(data)

        return count
    except Exception:
        logger.exception("clear_warnings_all error")
        return 0


def remove_warning_at_index(guild_id: int, user_id: int, index: int) -> bool:
    try:
        data = load_warnings()
        g_id = str(guild_id)
        u_id = str(user_id)

        warns = data.get(g_id, {}).get(u_id, [])
        if not warns or index < 1 or index > len(warns):
            return False

        warns.pop(index - 1)

        if warns:
            data[g_id][u_id] = warns
        else:
            if g_id in data and u_id in data[g_id]:
                del data[g_id][u_id]

        save_warnings(data)
        return True
    except Exception:
        logger.exception("remove_warning_at_index error")
        return False


def load_birthdays() -> dict:
    if not BIRTHDAY_FILE.exists():
        return {}
    try:
        with BIRTHDAY_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.warning("birthdays.json ist kaputt/leer -> starte mit {}")
        return {}
    except Exception:
        logger.exception("load_birthdays error")
        return {}


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


def get_birthday_text(guild_id: int | None, user_id: int) -> str:
    try:
        if guild_id is None:
            return "Nicht verfügbar"
        data = load_birthdays()
        g_id = str(guild_id)
        u_id = str(user_id)
        info = data.get(g_id, {}).get(u_id)
        if not info:
            return "Kein Geburtstag gespeichert"
        day = info.get("day")
        month = info.get("month")
        year = info.get("year")
        if day is None or month is None:
            return "Kein Geburtstag gespeichert"
        return format_birthday(day, month, year)
    except Exception:
        logger.exception("get_birthday_text error")
        return "Kein Geburtstag gespeichert"


def format_dt(dt: discord.utils.snowflake_time | None) -> str:
    try:
        if dt is None:
            return "Unbekannt"
        ts = int(dt.timestamp())
        return f"<t:{ts}:F> (<t:{ts}:R>)"
    except Exception:
        logger.exception("format_dt error")
        return "Unbekannt"


class UserManagementCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

        birthday_text = get_birthday_text(guild.id, member.id)

        embed = discord.Embed(
            title=f"Benutzerinfo – {member}",
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

        count = add_warning(interaction.guild.id, user.id, interaction.user.id, grund)
        reason_text = grund or "Kein Grund angegeben"

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

        warns = get_warnings(interaction.guild.id, user.id)

        if not warns:
            await interaction.response.send_message(
                f"{user.mention} hat bisher keine Verwarnungen.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Verwarnungen – {user}",
            color=discord.Color.orange(),
        )

        for idx, entry in enumerate(warns, start=1):
            mod_id = entry.get("moderator_id")
            mod_mention = f"<@{mod_id}>" if mod_id else "Unbekannt"
            reason = entry.get("reason", "Kein Grund angegeben")
            ts_iso = entry.get("timestamp")

            try:
                ts = (
                    discord.utils.parse_time(ts_iso)
                    if hasattr(discord.utils, "parse_time")
                    else None
                )
            except Exception:
                ts = None

            time_text = format_dt(ts) if ts else (ts_iso or "Unbekannt")

            embed.add_field(
                name=f"Verwarnung #{idx}",
                value=f"**Moderator:** {mod_mention}\n**Zeit:** {time_text}\n**Grund:** {reason}",
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

        if index is not None:
            ok = remove_warning_at_index(interaction.guild.id, user.id, index)
            if not ok:
                count_now = len(get_warnings(interaction.guild.id, user.id))
                await interaction.response.send_message(
                    f"Ungültiger Index. {user.mention} hat **{count_now}** Verwarnung(en).",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"✅ Verwarnung #{index} von {user.mention} wurde gelöscht.",
                ephemeral=True,
            )
            return

        count = clear_warnings_all(interaction.guild.id, user.id)
        if count <= 0:
            await interaction.response.send_message(
                f"{user.mention} hat keine Verwarnungen, die gelöscht werden können.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Alle Verwarnungen von {user.mention} wurden gelöscht. (Gelöscht: **{count}**)",
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
