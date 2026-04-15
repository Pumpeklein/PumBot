from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from src.mypackage import config
from src.mypackage.bot import logger

BASE_DIR = Path(__file__).resolve().parent.parent
COUNT_FILE = BASE_DIR / "database" / "counting.json"


def _load_data() -> Dict[str, Any]:
    try:
        if not COUNT_FILE.exists():
            return {"guilds": {}}
        with COUNT_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Fehler beim Laden der Counting-Datei")
        return {"guilds": {}}


def _save_data(data: Dict[str, Any]) -> None:
    try:
        COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with COUNT_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        logger.exception("Fehler beim Speichern der Counting-Datei")


def _get_guild_cfg(guild_id: int) -> Dict[str, Any]:
    data = _load_data()
    return data.get("guilds", {}).get(str(guild_id), {})


def _set_guild_cfg(guild_id: int, cfg: Dict[str, Any]) -> None:
    data = _load_data()
    guilds = data.setdefault("guilds", {})
    guilds[str(guild_id)] = cfg
    _save_data(data)


def _default_user_stats() -> Dict[str, int]:
    return {
        "correct": 0,
        "fails": 0,
        "best_streak": 0,
        "current_streak": 0,
    }


def _has_any_role(member: discord.Member, role_ids: set[int]) -> bool:
    return any(r.id in role_ids for r in member.roles)


class CountingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    counting = app_commands.Group(
        name="counting",
        description="Zähl-Channel konfigurieren und verwalten.",
    )

    def _is_allowed_staff(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        if guild is None:
            return False

        user = interaction.user
        if not isinstance(user, discord.Member):
            return False

        if user.guild_permissions.administrator:
            return True

        role_ids = set(getattr(config, "COUNTING_STAFF_ROLE_IDS", []))
        if role_ids:
            return _has_any_role(user, role_ids)

        role_names = set(
            getattr(
                config,
                "COUNTING_STAFF_ROLE_NAMES",
                ["Twitch Moderator", "Discord Moderator", "Team"],
            )
        )
        return any(r.name in role_names for r in user.roles)

    def _get_channel_id(self, guild_id: int) -> Optional[int]:
        cfg = _get_guild_cfg(guild_id)
        return cfg.get("channel_id")

    def _get_last_number(self, guild_id: int) -> int:
        cfg = _get_guild_cfg(guild_id)
        return int(cfg.get("last_number", 0))

    def _get_last_user(self, guild_id: int) -> Optional[int]:
        cfg = _get_guild_cfg(guild_id)
        return cfg.get("last_user_id")

    def _get_highscore(self, guild_id: int) -> int:
        cfg = _get_guild_cfg(guild_id)
        return int(cfg.get("highscore", 0))

    def _set_state(
        self,
        guild_id: int,
        channel_id: int,
        last_number: int,
        last_user_id: Optional[int] = None,
    ):
        cfg = _get_guild_cfg(guild_id)
        cfg["channel_id"] = channel_id
        cfg["last_number"] = int(last_number)
        if last_user_id is not None:
            cfg["last_user_id"] = int(last_user_id)
        else:
            cfg.pop("last_user_id", None)
        _set_guild_cfg(guild_id, cfg)

    def _set_highscore(self, guild_id: int, value: int):
        cfg = _get_guild_cfg(guild_id)
        cfg["highscore"] = int(value)
        _set_guild_cfg(guild_id, cfg)

    def _get_user_stats(self, guild_id: int, user_id: int) -> Dict[str, int]:
        cfg = _get_guild_cfg(guild_id)
        users = cfg.get("users", {})
        raw = users.get(str(user_id))
        if not isinstance(raw, dict):
            return _default_user_stats()
        stats = _default_user_stats()
        stats.update({k: int(raw.get(k, v)) for k, v in stats.items()})
        return stats

    def _set_user_stats(
        self, guild_id: int, user_id: int, stats: Dict[str, int]
    ) -> None:
        cfg = _get_guild_cfg(guild_id)
        users = cfg.setdefault("users", {})
        users[str(user_id)] = {
            "correct": int(stats.get("correct", 0)),
            "fails": int(stats.get("fails", 0)),
            "best_streak": int(stats.get("best_streak", 0)),
            "current_streak": int(stats.get("current_streak", 0)),
        }
        cfg["users"] = users
        _set_guild_cfg(guild_id, cfg)

    def _update_user_correct(self, guild_id: int, user_id: int) -> None:
        stats = self._get_user_stats(guild_id, user_id)
        stats["correct"] += 1
        stats["current_streak"] += 1
        if stats["current_streak"] > stats["best_streak"]:
            stats["best_streak"] = stats["current_streak"]
        self._set_user_stats(guild_id, user_id, stats)

    def _update_user_fail(self, guild_id: int, user_id: int) -> None:
        stats = self._get_user_stats(guild_id, user_id)
        stats["fails"] += 1
        stats["current_streak"] = 0
        self._set_user_stats(guild_id, user_id, stats)

    async def _handle_correct_number(
        self, message: discord.Message, current_number: int
    ) -> None:
        try:
            guild_id = message.guild.id  # type: ignore

            highscore = self._get_highscore(guild_id)
            if current_number > highscore:
                self._set_highscore(guild_id, current_number)

            self._update_user_correct(guild_id, message.author.id)
            self._set_state(
                guild_id, message.channel.id, current_number, message.author.id
            )
            await message.add_reaction("✅")
        except Exception:
            logger.exception("Fehler beim Verarbeiten einer korrekten Zahl")

    async def _handle_wrong_number(
        self, message: discord.Message, expected: int, reason: str
    ) -> None:
        try:
            guild_id = message.guild.id  # type: ignore

            self._update_user_fail(guild_id, message.author.id)
            self._set_state(guild_id, message.channel.id, 0, None)

            await message.reply(
                f"{message.author.mention} hat verkackt!\n"
                f"Grund: **{reason}**\n"
                "Der Zähler wurde zurückgesetzt, es startet wieder bei **1**.",
                mention_author=False,
            )
        except Exception:
            logger.exception("Fehler beim Verarbeiten einer falschen Zahl")

    @counting.command(
        name="setchannel",
        description="Legt den Channel fest, in dem gezählt werden soll.",
    )
    async def counting_setchannel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not self._is_allowed_staff(interaction):
            await interaction.response.send_message(
                "Dafür hast du keine Berechtigung.", ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        self._set_state(guild.id, channel.id, 0, None)

        await interaction.response.send_message(
            f"Counting-Channel wurde auf {channel.mention} gesetzt.\n"
            "Der Zähler startet wieder bei **1**.",
            ephemeral=True,
        )

    @counting.command(
        name="reset",
        description="Setzt den Zähler manuell zurück (nächste Zahl = 1).",
    )
    async def counting_reset(self, interaction: discord.Interaction):
        if not self._is_allowed_staff(interaction):
            await interaction.response.send_message(
                "Dafür hast du keine Berechtigung.", ephemeral=True
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        channel_id = self._get_channel_id(guild.id)
        if channel_id is None:
            await interaction.response.send_message(
                "Es ist kein Counting-Channel gesetzt.",
                ephemeral=True,
            )
            return

        self._set_state(guild.id, channel_id, 0, None)

        await interaction.response.send_message(
            "Der Zähler wurde zurückgesetzt. Nächste Zahl ist **1**.",
            ephemeral=True,
        )

    @counting.command(
        name="info",
        description="Zeigt Zählerstand, gesetzten Channel, letzte Person, Highscore und deine Streak an.",
    )
    async def counting_info(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        guild_id = guild.id
        channel_id = self._get_channel_id(guild_id)
        last = self._get_last_number(guild_id)
        last_user_id = self._get_last_user(guild_id)
        highscore = self._get_highscore(guild_id)

        if channel_id is None:
            await interaction.response.send_message(
                "Es ist aktuell **kein** Counting-Channel gesetzt.",
                ephemeral=True,
            )
            return

        channel = guild.get_channel(channel_id)
        last_user = guild.get_member(last_user_id) if last_user_id else None
        your_stats = self._get_user_stats(guild_id, interaction.user.id)

        await interaction.response.send_message(
            f"Counting-Channel: {channel.mention if channel else f'`#{channel_id}`'}\n"
            f"Letzte korrekte Zahl: **{last}**\n"
            f"Nächste Zahl: **{last + 1}**\n"
            f"Letzter Zähler: {last_user.mention if last_user else '—'}\n"
            f"Highscore (Server): **{highscore}**\n\n"
            "**Deine Stats:**\n"
            f"- Korrekte Zahlen: **{your_stats['correct']}**\n"
            f"- Fails: **{your_stats['fails']}**\n"
            f"- Beste Streak: **{your_stats['best_streak']}**\n"
            f"- Aktuelle Streak: **{your_stats['current_streak']}**",
            ephemeral=True,
        )

    @counting.command(
        name="leaderboard",
        description="Zeigt das Leaderboard für Counting (Top 10).",
    )
    async def counting_leaderboard(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        guild_id = guild.id
        cfg = _get_guild_cfg(guild_id)
        users: Dict[str, Any] = cfg.get("users", {})

        if not users:
            await interaction.response.send_message(
                "Es gibt noch keine Statistiken. Fangt erstmal mit dem Zählen an!",
                ephemeral=True,
            )
            return

        entries = []
        for user_id_str, stats_raw in users.items():
            try:
                user_id_int = int(user_id_str)
            except ValueError:
                continue
            stats = _default_user_stats()
            if isinstance(stats_raw, dict):
                for k in stats.keys():
                    if k in stats_raw:
                        try:
                            stats[k] = int(stats_raw[k])
                        except (TypeError, ValueError):
                            pass
            entries.append((user_id_int, stats))

        top_by_correct = sorted(entries, key=lambda e: e[1]["correct"], reverse=True)[
            :10
        ]
        top_by_streak = sorted(
            entries, key=lambda e: e[1]["best_streak"], reverse=True
        )[:10]

        embed = discord.Embed(
            title="📊 Counting Leaderboard",
            description=f"Server: {guild.name}",
            color=discord.Color.blurple(),
        )

        if top_by_correct:
            lines_correct = []
            for rank, (user_id_int, stats) in enumerate(top_by_correct, start=1):
                member = guild.get_member(user_id_int)
                name = member.mention if member else f"`{user_id_int}`"
                lines_correct.append(
                    f"**#{rank}** {name} – ✅ {stats['correct']} | Bestreak: {stats['best_streak']}"
                )
            embed.add_field(
                name="Top 10 – Korrekte Zahlen",
                value="\n".join(lines_correct),
                inline=False,
            )

        if top_by_streak:
            lines_streak = []
            for rank, (user_id_int, stats) in enumerate(top_by_streak, start=1):
                member = guild.get_member(user_id_int)
                name = member.mention if member else f"`{user_id_int}`"
                if stats["best_streak"] <= 0:
                    continue
                lines_streak.append(
                    f"**#{rank}** {name} – 🔥 Beste Streak: {stats['best_streak']} (✅ {stats['correct']})"
                )

            if lines_streak:
                embed.add_field(
                    name="Top 10 – Beste Streak",
                    value="\n".join(lines_streak),
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if message.author.bot:
                return
            if not message.guild:
                return

            guild_id = message.guild.id
            channel_id = self._get_channel_id(guild_id)

            if channel_id is None:
                return
            if message.channel.id != channel_id:
                return

            content = message.content.strip()

            if not content.isdigit():
                expected = self._get_last_number(guild_id) + 1
                await self._handle_wrong_number(message, expected, "Keine gültige Zahl")
                return

            number = int(content)
            if number <= 0:
                expected = self._get_last_number(guild_id) + 1
                await self._handle_wrong_number(
                    message, expected, "Zahl muss positiv sein"
                )
                return

            last_number = self._get_last_number(guild_id)
            expected = last_number + 1

            last_user_id = self._get_last_user(guild_id)
            if last_user_id == message.author.id:
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
