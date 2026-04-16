from __future__ import annotations

import re
from datetime import date
from typing import Optional, Dict

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.pumbot.utils.datetime_format import berlin_today

BIRTHDAY_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}

MONTH_NAMES_DE = {
    1: "Januar", 2: "Februar", 3: "März", 4: "April",
    5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
    9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
}


def is_birthday_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(role.name in BIRTHDAY_STAFF_ROLES for role in member.roles)


def parse_birthday(date_str: str) -> tuple[int, int, Optional[int]]:
    date_str = date_str.strip()
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?", date_str)
    if not match:
        raise ValueError("Ungültiges Datumsformat. Nutze TT.MM oder TT.MM.JJ/TT.MM.JJJJ.")

    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)

    if not 1 <= day <= 31 or not 1 <= month <= 12:
        raise ValueError("Tag oder Monat ist ungültig.")

    year: Optional[int] = None

    if year_raw is not None:
        year_int = int(year_raw)
        year = year_int
        check_year = 2000 + year_int if year_int < 100 else year_int
    else:
        check_year = 2000

    try:
        date(check_year, month, day)
    except ValueError:
        raise ValueError("Dieses Datum existiert nicht.")

    return day, month, year


def format_birthday(day: int, month: int, year: Optional[int]) -> str:
    if year is None:
        return f"{day:02d}.{month:02d}"
    if year < 100:
        return f"{day:02d}.{month:02d}.{year:02d}"
    return f"{day:02d}.{month:02d}.{year:04d}"


def calculate_age(day: int, month: int, year: Optional[int]) -> Optional[int]:
    if year is None:
        return None
    if year < 100:
        year = 2000 + year
    if year < 1900:
        return None
    today = berlin_today()
    age = today.year - year
    if (month, day) > (today.month, today.day):
        age -= 1
    if age < 0 or age > 150:
        return None
    return age


class BirthdayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self.birthday_check_loop.start()

    def cog_unload(self):
        self.birthday_check_loop.cancel()

    async def _build_birthday_embed(self, guild: discord.Guild) -> Optional[discord.Embed]:
        g_id = str(guild.id)
        birthdays = await self.api.get_birthdays(g_id)
        if not birthdays:
            return None

        by_month: Dict[int, list] = {m: [] for m in range(1, 13)}
        for b in birthdays:
            user = guild.get_member(int(b["user_id"]))
            display_name = user.display_name if user else f"Unbekannt ({b['user_id']})"
            by_month[b["month"]].append((b["day"], display_name, b.get("year")))

        if not any(by_month[m] for m in by_month):
            return None

        embed = discord.Embed(
            title=f"\U0001f389 Geburtstagsliste \u2013 {guild.name}",
            description="Alle eingetragenen Geburtstage, sortiert nach Monaten.",
            color=discord.Color.gold(),
        )

        for month in range(1, 13):
            entries = by_month[month]
            if entries:
                entries.sort(key=lambda x: x[0])
                lines = [
                    f"**{day:02d}.** \u2013 {name} ({format_birthday(day, month, year)})"
                    for day, name, year in entries
                ]
                value = "\n".join(lines)
                if len(value) > 1024:
                    value = value[:1000] + "\n\u2026 (gekürzt)"
            else:
                value = "\u200b"
            embed.add_field(name=MONTH_NAMES_DE.get(month, f"Monat {month}"), value=value, inline=False)

        return embed

    async def _update_birthday_list_message(self, guild: discord.Guild) -> None:
        g_id = str(guild.id)
        list_channel_id = await self.api.get_config(g_id, "birthday_list_channel_id")
        list_message_id = await self.api.get_config(g_id, "birthday_list_message_id")

        if not list_channel_id or not list_message_id:
            return

        channel = guild.get_channel(int(list_channel_id))
        if not isinstance(channel, discord.TextChannel):
            return

        embed = await self._build_birthday_embed(guild)
        if embed is None:
            embed = discord.Embed(
                title=f"\U0001f389 Geburtstagsliste \u2013 {guild.name}",
                description="Für diesen Server sind noch keine Geburtstage gespeichert.",
                color=discord.Color.gold(),
            )

        try:
            msg = await channel.fetch_message(int(list_message_id))
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden):
            pass
        except discord.HTTPException:
            return

    birthdays_group = app_commands.Group(
        name="geburtstage", description="Geburtstage verwalten und anzeigen.",
    )

    @birthdays_group.command(
        name="set",
        description="Speichere oder ändere deinen Geburtstag (TT.MM oder TT.MM.JJ).",
    )
    @app_commands.describe(datum="Geburtstag im Format TT.MM oder TT.MM.JJ/TT.MM.JJJJ")
    async def birthdays_set(self, interaction: discord.Interaction, datum: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )
            return
        try:
            day, month, year = parse_birthday(datum)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        await self.api.set_birthday(str(interaction.guild.id), str(interaction.user.id), day, month, year)

        await interaction.response.send_message(
            f"Dein Geburtstag wurde gespeichert als **{format_birthday(day, month, year)}**.",
            ephemeral=True,
        )
        await self._update_birthday_list_message(interaction.guild)

    @birthdays_group.command(name="remove", description="Entferne deinen gespeicherten Geburtstag.")
    async def birthdays_remove(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )
            return

        existing = await self.api.get_birthday(str(interaction.guild.id), str(interaction.user.id))
        if existing:
            await self.api.delete_birthday(str(interaction.guild.id), str(interaction.user.id))
            await interaction.response.send_message("Dein Geburtstag wurde entfernt.", ephemeral=True)
            await self._update_birthday_list_message(interaction.guild)
        else:
            await interaction.response.send_message(
                "Für dich ist kein Geburtstag gespeichert.", ephemeral=True,
            )

    @birthdays_group.command(
        name="list",
        description="Zeigt die Geburtstagsliste an und speichert diese Nachricht als Liste.",
    )
    async def birthdays_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )
            return

        embed = await self._build_birthday_embed(guild)
        if embed is None:
            embed = discord.Embed(
                title=f"\U0001f389 Geburtstagsliste \u2013 {guild.name}",
                description="Für diesen Server sind noch keine Geburtstage gespeichert.",
                color=discord.Color.gold(),
            )

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        g_id = str(guild.id)
        await self.api.set_config(g_id, "birthday_list_channel_id", str(msg.channel.id))
        await self.api.set_config(g_id, "birthday_list_message_id", str(msg.id))

    @birthdays_group.command(
        name="set_user", description="Setzt den Geburtstag eines Users (Staff).",
    )
    @app_commands.describe(user="User", datum="Geburtstag im Format TT.MM oder TT.MM.JJ/TT.MM.JJJJ")
    async def birthdays_set_user(
        self, interaction: discord.Interaction, user: discord.Member, datum: str
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )
            return
        if not is_birthday_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return
        try:
            day, month, year = parse_birthday(datum)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        await self.api.set_birthday(str(interaction.guild.id), str(user.id), day, month, year)

        await interaction.response.send_message(
            f"Geburtstag für {user.mention} wurde gesetzt auf **{format_birthday(day, month, year)}**.",
            ephemeral=True,
        )
        await self._update_birthday_list_message(interaction.guild)

    @birthdays_group.command(
        name="set_channel",
        description="Setzt den Channel für automatische Geburtstags-Gratulationen (Staff).",
    )
    @app_commands.describe(channel="Textkanal für Gratulationen")
    async def birthdays_set_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True,
            )
            return
        if not is_birthday_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        await self.api.set_config(str(interaction.guild.id), "birthday_channel_id", str(channel.id))

        await interaction.response.send_message(
            f"Birthday-Channel wurde auf {channel.mention} gesetzt.", ephemeral=True
        )

    @tasks.loop(minutes=1)
    async def birthday_check_loop(self):
        await self.bot.wait_until_ready()

        today = berlin_today()
        today_iso = today.isoformat()

        for guild in self.bot.guilds:
            g_id = str(guild.id)

            channel_id_str = await self.api.get_config(g_id, "birthday_channel_id")
            if not channel_id_str:
                continue

            channel = guild.get_channel(int(channel_id_str))
            if not isinstance(channel, discord.TextChannel):
                continue

            birthdays_today = await self.api.get_birthdays_today(g_id)
            for b in birthdays_today:
                if b.get("last_congrats") == today_iso:
                    continue

                member = guild.get_member(int(b["user_id"]))
                if member is None:
                    continue

                age = calculate_age(b["day"], b["month"], b.get("year"))
                if age is not None:
                    msg_text = (
                        f"\U0001f389\U0001f382 Alles Gute zum Geburtstag, {member.mention}! \U0001f382\U0001f389\n"
                        f"Du wirst heute **{age}** Jahre alt \u2013 wir wünschen dir einen wundervollen Tag!"
                    )
                else:
                    msg_text = (
                        f"\U0001f389\U0001f382 Alles Gute zum Geburtstag, {member.mention}! \U0001f382\U0001f389\n"
                        f"Wir wünschen dir einen wundervollen Tag!"
                    )

                try:
                    await channel.send(msg_text)
                except discord.Forbidden:
                    continue

                await self.api.mark_birthday_congrats(g_id, b["user_id"])

    @birthday_check_loop.error
    async def birthday_check_loop_error(self, error: Exception):
        return


async def setup(bot: commands.Bot):
    await bot.add_cog(BirthdayCog(bot))
