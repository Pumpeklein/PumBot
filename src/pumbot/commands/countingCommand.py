from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot import config
from src.pumbot.bot import logger


def _default_user_stats() -> Dict[str, int]:
    return {"correct": 0, "fails": 0, "best_streak": 0, "current_streak": 0}


IGNORED_COUNTING_TOKENS_RE = re.compile(
    r"<(?:#|@!?|@&)\d+>|<a?:[A-Za-z0-9_]+:\d+>|:[^:\s]+:"
)
COUNTING_NUMBER_RE = re.compile(r"\d+")


def _extract_counting_number(content: str) -> Optional[int]:
    cleaned = IGNORED_COUNTING_TOKENS_RE.sub(" ", content)
    match = COUNTING_NUMBER_RE.search(cleaned)
    if match is None:
        return None
    return int(match.group(0))


class CountingCog(commands.Cog):
    CONFIRM_REACTION_DELAY_SECONDS = 0.5

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self._channel_cache: dict[int, Optional[int]] = {}
        self._state_cache: dict[int, dict] = {}

    async def _get_state(self, guild_id: int) -> dict:
        if guild_id in self._state_cache:
            return self._state_cache[guild_id]
        raw = await self.api.get_counting(str(guild_id))
        state = raw or {
            "channel_id": None,
            "last_number": 0,
            "last_user_id": None,
            "highscore": 0,
        }
        self._state_cache[guild_id] = state
        return state

    async def _save_state(self, guild_id: int, **kwargs: Any) -> None:
        state = await self._get_state(guild_id)
        state.update(kwargs)
        self._state_cache[guild_id] = state
        await self.api.set_counting(str(guild_id), **kwargs)

    async def _get_channel_id(self, guild_id: int) -> Optional[int]:
        if guild_id in self._channel_cache:
            return self._channel_cache[guild_id]
        state = await self._get_state(guild_id)
        ch = int(state["channel_id"]) if state.get("channel_id") else None
        self._channel_cache[guild_id] = ch
        return ch

    async def _get_user_stats(self, guild_id: int, user_id: int) -> Dict[str, int]:
        raw = await self.api.get_counting_stats(str(guild_id), str(user_id))
        if not raw:
            return _default_user_stats()
        stats = _default_user_stats()
        for k in stats:
            if k in raw:
                stats[k] = int(raw[k])
        return stats

    async def _save_user_stats(
        self, guild_id: int, user_id: int, stats: Dict[str, int]
    ) -> None:
        await self.api.set_counting_stats(str(guild_id), str(user_id), **stats)

    async def _update_user_correct(self, guild_id: int, user_id: int) -> None:
        stats = await self._get_user_stats(guild_id, user_id)
        stats["correct"] += 1
        stats["current_streak"] += 1
        if stats["current_streak"] > stats["best_streak"]:
            stats["best_streak"] = stats["current_streak"]
        await self._save_user_stats(guild_id, user_id, stats)

    async def _update_user_fail(self, guild_id: int, user_id: int) -> None:
        stats = await self._get_user_stats(guild_id, user_id)
        stats["fails"] += 1
        stats["current_streak"] = 0
        await self._save_user_stats(guild_id, user_id, stats)

    def _is_allowed_staff(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        if guild is None:
            return False
        user = interaction.user
        if not isinstance(user, discord.Member):
            return False
        if user.guild_permissions.administrator:
            return True
        role_names = {"Twitch Moderator", "Discord Moderator", "Team", "Admin"}
        return any(r.name in role_names for r in user.roles)

    async def _handle_correct_number(
        self, message: discord.Message, current_number: int
    ) -> None:
        try:
            guild_id = message.guild.id
            state = await self._get_state(guild_id)
            highscore = int(state.get("highscore", 0))
            new_hs = max(highscore, current_number)
            await self._save_state(
                guild_id,
                last_number=current_number,
                last_user_id=message.author.id,
                highscore=new_hs,
            )
            await self._update_user_correct(guild_id, message.author.id)
            await asyncio.sleep(self.CONFIRM_REACTION_DELAY_SECONDS)
            await message.add_reaction("\u2705")
        except Exception:
            logger.exception("Fehler beim Verarbeiten einer korrekten Zahl")

    async def _handle_wrong_number(
        self, message: discord.Message, expected: int, reason: str
    ) -> None:
        try:
            guild_id = message.guild.id
            await self._update_user_fail(guild_id, message.author.id)
            await self._save_state(guild_id, last_number=0, last_user_id=None)
            await message.reply(
                f"{message.author.mention} hat verkackt!\n"
                f"Grund: **{reason}**\n"
                "Der Zähler wurde zurückgesetzt, es startet wieder bei **1**.",
                mention_author=False,
            )
        except Exception:
            logger.exception("Fehler beim Verarbeiten einer falschen Zahl")

    counting = app_commands.Group(
        name="counting",
        description="Zähl-Channel konfigurieren und verwalten.",
    )

    @counting.command(
        name="setchannel",
        description="Legt den Channel fest, in dem gezählt werden soll.",
    )
    async def counting_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not self._is_allowed_staff(interaction):
            return await interaction.response.send_message(
                "Dafür hast du keine Berechtigung.", ephemeral=True
            )
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        await self._save_state(
            guild.id, channel_id=str(channel.id), last_number=0, last_user_id=None
        )
        self._channel_cache[guild.id] = channel.id
        self._state_cache.pop(guild.id, None)

        await interaction.response.send_message(
            f"Counting-Channel wurde auf {channel.mention} gesetzt.\n"
            "Der Zähler startet wieder bei **1**.",
            ephemeral=True,
        )

    @counting.command(name="reset", description="Setzt den Zähler manuell zurück.")
    async def counting_reset(self, interaction: discord.Interaction):
        if not self._is_allowed_staff(interaction):
            return await interaction.response.send_message(
                "Dafür hast du keine Berechtigung.", ephemeral=True
            )
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        channel_id = await self._get_channel_id(guild.id)
        if channel_id is None:
            return await interaction.response.send_message(
                "Es ist kein Counting-Channel gesetzt.",
                ephemeral=True,
            )

        await self._save_state(guild.id, last_number=0, last_user_id=None)
        self._state_cache.pop(guild.id, None)

        await interaction.response.send_message(
            "Der Zähler wurde zurückgesetzt. Nächste Zahl ist **1**.",
            ephemeral=True,
        )

    @counting.command(name="info", description="Zeigt Zählerstand und Stats.")
    async def counting_info(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        state = await self._get_state(guild.id)
        channel_id = int(state["channel_id"]) if state.get("channel_id") else None
        if channel_id is None:
            return await interaction.response.send_message(
                "Es ist aktuell **kein** Counting-Channel gesetzt.",
                ephemeral=True,
            )

        last = int(state.get("last_number", 0))
        last_uid = state.get("last_user_id")
        highscore = int(state.get("highscore", 0))
        channel = guild.get_channel(channel_id)
        last_user_display = f"<@{last_uid}>" if last_uid else chr(8212)
        your_stats = await self._get_user_stats(guild.id, interaction.user.id)

        await interaction.response.send_message(
            f"Counting-Channel: {channel.mention if channel else f'`#{channel_id}`'}\n"
            f"Letzte korrekte Zahl: **{last}**\n"
            f"Nächste Zahl: **{last + 1}**\n"
            f"Letzter Zähler: {last_user_display}\n"
            f"Highscore (Server): **{highscore}**\n\n"
            "**Deine Stats:**\n"
            f"- Korrekte Zahlen: **{your_stats['correct']}**\n"
            f"- Fails: **{your_stats['fails']}**\n"
            f"- Beste Streak: **{your_stats['best_streak']}**\n"
            f"- Aktuelle Streak: **{your_stats['current_streak']}**",
            ephemeral=True,
        )

    @counting.command(name="leaderboard", description="Zeigt das Leaderboard (Top 10).")
    async def counting_leaderboard(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )

        entries = await self.api.get_counting_leaderboard(str(guild.id), limit=10)
        if not entries:
            return await interaction.response.send_message(
                "Es gibt noch keine Statistiken.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title="\U0001f4ca Counting Leaderboard",
            description=f"Server: {guild.name}",
            color=discord.Color.blurple(),
        )

        lines = []
        for rank, e in enumerate(entries, start=1):
            name = f"<@{e['user_id']}>"
            lines.append(
                f"**#{rank}** {name} \u2013 \u2705 {e.get('correct', 0)} | Best-Streak: {e.get('best_streak', 0)}"
            )

        embed.add_field(
            name="Top 10 \u2013 Korrekte Zahlen", value="\n".join(lines), inline=False
        )
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if message.author.bot or not message.guild:
                return

            guild_id = message.guild.id
            channel_id = await self._get_channel_id(guild_id)
            if channel_id is None or message.channel.id != channel_id:
                return

            content = message.content.strip()
            state = await self._get_state(guild_id)
            last_number = int(state.get("last_number", 0))
            expected = last_number + 1

            number = _extract_counting_number(content)
            if number is None:
                await self._handle_wrong_number(message, expected, "Keine gültige Zahl")
                return

            if number <= 0:
                await self._handle_wrong_number(
                    message, expected, "Zahl muss positiv sein"
                )
                return

            last_user_id = state.get("last_user_id")
            if last_user_id and int(last_user_id) == message.author.id:
                await self._handle_wrong_number(
                    message, expected, "Du darfst nicht zweimal hintereinander zählen"
                )
                return

            if number != expected:
                await self._handle_wrong_number(message, expected, "Falsche Zahl")
                return

            await self._handle_correct_number(message, number)

        except Exception:
            logger.exception("Fehler im Counting-System")


async def setup(bot: commands.Bot):
    await bot.add_cog(CountingCog(bot))
