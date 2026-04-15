from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, Any, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

DATA_DIR = Path("data")
BIRTHDAY_FILE = DATA_DIR / "birthdays.json"

BIRTHDAY_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}

MONTH_NAMES_DE = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
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
        if year_int < 100:
            check_year = 2000 + year_int
        else:
            check_year = year_int
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

    today = date.today()
    age = today.year - year
    if (month, day) > (today.month, today.day):
        age -= 1
    if age < 0 or age > 150:
        return None
    return age


def load_birthdays() -> Dict[str, Any]:
    if BIRTHDAY_FILE.exists():
        try:
            with BIRTHDAY_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}


def save_birthdays(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with BIRTHDAY_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


class BirthdayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.birthday_check_loop.start()

    def cog_unload(self):
        self.birthday_check_loop.cancel()

    def _build_birthday_embed(self, guild: discord.Guild) -> Optional[discord.Embed]:
        data = load_birthdays()
        g_id = str(guild.id)

        if g_id not in data:
            return None

        guild_data = data[g_id]
        by_month: Dict[int, list[tuple[int, str, Optional[int]]]] = {m: [] for m in range(1, 13)}

        for user_id_str, info in guild_data.items():
            if user_id_str == "_config":
                continue

            user = guild.get_member(int(user_id_str))
            display_name = user.display_name if user else f"Unbekannt ({user_id_str})"
            day = info["day"]
            month = info["month"]
            year = info.get("year")
            by_month[month].append((day, display_name, year))

        if not any(by_month[m] for m in by_month):
            return None

        embed = discord.Embed(
            title=f"🎉 Geburtstagsliste – {guild.name}",
            description="Alle eingetragenen Geburtstage, sortiert nach Monaten.",
            color=discord.Color.gold(),
        )

        for month in range(1, 13):
            entries = by_month[month]

            if entries:
                entries.sort(key=lambda x: x[0])
                lines = []
                for day, name, year in entries:
                    lines.append(f"**{day:02d}.** – {name} ({format_birthday(day, month, year)})")

                value = "\n".join(lines)
                if len(value) > 1024:
                    value = value[:1000] + "\n… (gekürzt)"
            else:
                value = "\u200b"

            month_name = MONTH_NAMES_DE.get(month, f"Monat {month}")
            embed.add_field(name=month_name, value=value, inline=False)

        return embed

    async def _update_birthday_list_message(self, guild: discord.Guild) -> None:
        data = load_birthdays()
        g_id = str(guild.id)
        g_data = data.get(g_id)
        if not g_data:
            return

        config = g_data.get("_config", {})
        list_channel_id = config.get("list_channel_id")
        list_message_id = config.get("list_message_id")

        if not list_channel_id or not list_message_id:
            return

        channel = guild.get_channel(list_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        embed = self._build_birthday_embed(guild)
        if embed is None:
            embed = discord.Embed(
                title=f"🎉 Geburtstagsliste – {guild.name}",
                description="Für diesen Server sind noch keine Geburtstage gespeichert.",
                color=discord.Color.gold(),
            )

        try:
            msg = await channel.fetch_message(list_message_id)
            await msg.edit(embed=embed)
        except (discord.NotFound, discord.Forbidden):
            config.pop("list_channel_id", None)
            config.pop("list_message_id", None)
            g_data["_config"] = config
            save_birthdays(data)
        except discord.HTTPException:
            return

    birthdays_group = app_commands.Group(
        name="geburtstage",
        description="Geburtstage verwalten und anzeigen.",
    )

    @birthdays_group.command(name="set", description="Speichere oder ändere deinen Geburtstag (TT.MM oder TT.MM.JJ).")
    @app_commands.describe(datum="Geburtstag im Format TT.MM oder TT.MM.JJ/TT.MM.JJJJ")
    async def birthdays_set(self, interaction: discord.Interaction, datum: str):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return

        try:
            day, month, year = parse_birthday(datum)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        data = load_birthdays()
        g_id = str(interaction.guild.id)
        u_id = str(interaction.user.id)

        if g_id not in data:
            data[g_id] = {}

        old_entry = data[g_id].get(u_id, {})
        last_congrats = old_entry.get("last_congrats")

        data[g_id][u_id] = {
            "day": day,
            "month": month,
            "year": year,
            "last_congrats": last_congrats,
        }
        save_birthdays(data)

        await interaction.response.send_message(
            f"Dein Geburtstag wurde gespeichert als **{format_birthday(day, month, year)}**.",
            ephemeral=True,
        )

        await self._update_birthday_list_message(interaction.guild)

    @birthdays_group.command(name="remove", description="Entferne deinen gespeicherten Geburtstag.")
    async def birthdays_remove(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return

        data = load_birthdays()
        g_id = str(interaction.guild.id)
        u_id = str(interaction.user.id)

        if g_id in data and u_id in data[g_id]:
            del data[g_id][u_id]
            save_birthdays(data)
            await interaction.response.send_message("Dein Geburtstag wurde entfernt.", ephemeral=True)
            await self._update_birthday_list_message(interaction.guild)
        else:
            await interaction.response.send_message("Für dich ist kein Geburtstag gespeichert.", ephemeral=True)

    @birthdays_group.command(name="list", description="Zeigt die Geburtstagsliste an und speichert diese Nachricht als Liste.")
    async def birthdays_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return

        embed = self._build_birthday_embed(guild)
        if embed is None:
            embed = discord.Embed(
                title=f"🎉 Geburtstagsliste – {guild.name}",
                description="Für diesen Server sind noch keine Geburtstage gespeichert.",
                color=discord.Color.gold(),
            )

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        data = load_birthdays()
        g_id = str(guild.id)
        if g_id not in data:
            data[g_id] = {}

        config = data[g_id].get("_config", {})
        config["list_channel_id"] = msg.channel.id
        config["list_message_id"] = msg.id
        data[g_id]["_config"] = config
        save_birthdays(data)

    @birthdays_group.command(name="set_user", description="Setzt den Geburtstag eines Users (Staff).")
    @app_commands.describe(user="User", datum="Geburtstag im Format TT.MM oder TT.MM.JJ/TT.MM.JJJJ")
    async def birthdays_set_user(self, interaction: discord.Interaction, user: discord.Member, datum: str):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return

        if not is_birthday_staff(interaction.user):
            await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
            return

        try:
            day, month, year = parse_birthday(datum)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        data = load_birthdays()
        g_id = str(interaction.guild.id)
        u_id = str(user.id)

        if g_id not in data:
            data[g_id] = {}

        old_entry = data[g_id].get(u_id, {})
        last_congrats = old_entry.get("last_congrats")

        data[g_id][u_id] = {
            "day": day,
            "month": month,
            "year": year,
            "last_congrats": last_congrats,
        }
        save_birthdays(data)

        await interaction.response.send_message(
            f"Geburtstag für {user.mention} wurde gesetzt auf **{format_birthday(day, month, year)}**.",
            ephemeral=True,
        )

        await self._update_birthday_list_message(interaction.guild)

    @birthdays_group.command(name="set_channel", description="Setzt den Channel für automatische Geburtstags-Gratulationen (Staff).")
    @app_commands.describe(channel="Textkanal für Gratulationen")
    async def birthdays_set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return

        if not is_birthday_staff(interaction.user):
            await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
            return

        data = load_birthdays()
        g_id = str(interaction.guild.id)

        if g_id not in data:
            data[g_id] = {}

        config = data[g_id].get("_config", {})
        config["channel_id"] = channel.id
        data[g_id]["_config"] = config

        save_birthdays(data)

        await interaction.response.send_message(f"Birthday-Channel wurde auf {channel.mention} gesetzt.", ephemeral=True)

    @tasks.loop(minutes=1)
    async def birthday_check_loop(self):
        await self.bot.wait_until_ready()

        today = discord.utils.utcnow().date()
        today_iso = today.isoformat()

        data = load_birthdays()
        changed = False

        for guild in self.bot.guilds:
            g_id = str(guild.id)
            g_data = data.get(g_id)
            if not g_data:
                continue

            config = g_data.get("_config", {})
            channel_id = config.get("channel_id")
            if not channel_id:
                continue

            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            for user_id_str, info in g_data.items():
                if user_id_str == "_config":
                    continue

                day = info.get("day")
                month = info.get("month")
                year = info.get("year")
                if day is None or month is None:
                    continue

                if day == today.day and month == today.month:
                    last_congrats = info.get("last_congrats")
                    if last_congrats == today_iso:
                        continue

                    member = guild.get_member(int(user_id_str))
                    if member is None:
                        continue

                    age = calculate_age(day, month, year)
                    if age is not None:
                        msg = (
                            f"🎉🎂 Alles Gute zum Geburtstag, {member.mention}! 🎂🎉\n"
                            f"Du wirst heute **{age}** Jahre alt – wir wünschen dir einen wundervollen Tag!"
                        )
                    else:
                        msg = (
                            f"🎉🎂 Alles Gute zum Geburtstag, {member.mention}! 🎂🎉\n"
                            f"Wir wünschen dir einen wundervollen Tag!"
                        )

                    try:
                        await channel.send(msg)
                    except discord.Forbidden:
                        continue

                    info["last_congrats"] = today_iso
                    g_data[user_id_str] = info
                    changed = True

            data[g_id] = g_data

        if changed:
            save_birthdays(data)

    @birthday_check_loop.error
    async def birthday_check_loop_error(self, error: Exception):
        return


async def setup(bot: commands.Bot):
    await bot.add_cog(BirthdayCog(bot))
