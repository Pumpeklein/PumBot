from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.pumbot.bot import logger

# Auftrag aus dem Web Panel in `guild_config`. Das Panel schreibt den Zaehlerstand
# nicht selbst: der Cache hier wuerde ihn sonst beim naechsten Speichern ueberschreiben.
PANEL_COMMAND_KEY = "counting_panel_command"


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
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self._channel_cache: dict[int, Optional[int]] = {}
        self._state_cache: dict[int, dict] = {}
        self._stats_cache: dict[tuple[int, int], Dict[str, int]] = {}
        # Bewertungs-Lock pro Guild: haelt die Nachrichten in Eingangsreihenfolge.
        self._eval_locks: dict[int, asyncio.Lock] = {}
        # Schreib-Lock pro Guild: die DB-Writes duerfen sich nicht ueberholen.
        self._write_locks: dict[int, asyncio.Lock] = {}
        self._pending_writes: set[asyncio.Task] = set()
        self.panel_commands.start()

    def cog_unload(self) -> None:
        self.panel_commands.cancel()

    @tasks.loop(seconds=15)
    async def panel_commands(self) -> None:
        """Uebernimmt Reset und Kanalwechsel aus dem Web Panel ueber denselben Weg wie die Befehle."""
        for guild in self.bot.guilds:
            guild_id = str(guild.id)
            raw = await self.api.get_config(guild_id, PANEL_COMMAND_KEY)
            if not raw:
                continue
            try:
                await self._apply_panel_command(guild.id, json.loads(raw))
            except (ValueError, TypeError):
                logger.warning("Ungueltiger Counting-Auftrag aus dem Panel: %r", raw)
            except Exception:
                logger.exception("Counting-Auftrag aus dem Panel fehlgeschlagen")
                continue
            # Nur loeschen, was bearbeitet wurde — ein neuer Auftrag bleibt fuer den naechsten Lauf.
            if await self.api.get_config(guild_id, PANEL_COMMAND_KEY) == raw:
                await self.api.delete_config(guild_id, PANEL_COMMAND_KEY)

    @panel_commands.before_loop
    async def _before_panel_commands(self) -> None:
        await self.bot.wait_until_ready()

    async def _apply_panel_command(self, guild_id: int, command: dict) -> None:
        action = command.get("action")
        channel_id = str(command.get("channel_id") or "")
        if action not in ("reset", "channel") or (action == "channel" and not channel_id.isdigit()):
            raise ValueError(action)

        # Wie /counting reset und /counting setchannel: laufende Bewertungen abwarten,
        # der Highscore bleibt stehen.
        async with self._lock_for(self._eval_locks, guild_id):
            if action == "channel":
                await self._save_state(
                    guild_id, channel_id=channel_id, last_number=0, last_user_id=None
                )
                self._channel_cache[guild_id] = int(channel_id)
            else:
                await self._save_state(guild_id, last_number=0, last_user_id=None)
            self._state_cache.pop(guild_id, None)
        logger.info("Counting-Auftrag %s aus dem Panel fuer Guild %s uebernommen.", action, guild_id)

    @staticmethod
    def _lock_for(locks: dict[int, asyncio.Lock], guild_id: int) -> asyncio.Lock:
        lock = locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[guild_id] = lock
        return lock

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

    def _apply_state(self, state: dict, guild_id: int, **kwargs: Any) -> dict:
        """Aktualisiert nur den Cache; der DB-Write laeuft getrennt davon."""
        state.update(kwargs)
        self._state_cache[guild_id] = state
        return state

    async def _save_state(self, guild_id: int, **kwargs: Any) -> None:
        self._apply_state(await self._get_state(guild_id), guild_id, **kwargs)
        async with self._lock_for(self._write_locks, guild_id):
            await self.api.set_counting(str(guild_id), **kwargs)

    async def _get_channel_id(self, guild_id: int) -> Optional[int]:
        if guild_id in self._channel_cache:
            return self._channel_cache[guild_id]
        state = await self._get_state(guild_id)
        ch = int(state["channel_id"]) if state.get("channel_id") else None
        self._channel_cache[guild_id] = ch
        return ch

    async def _get_user_stats(self, guild_id: int, user_id: int) -> Dict[str, int]:
        cached = self._stats_cache.get((guild_id, user_id))
        if cached is not None:
            return cached
        raw = await self.api.get_counting_stats(str(guild_id), str(user_id))
        stats = _default_user_stats()
        if raw:
            for k in stats:
                if k in raw:
                    stats[k] = int(raw[k])
        self._stats_cache[(guild_id, user_id)] = stats
        return stats

    async def _save_user_stats(
        self, guild_id: int, user_id: int, stats: Dict[str, int]
    ) -> None:
        self._stats_cache[(guild_id, user_id)] = stats
        await self.api.set_counting_stats(str(guild_id), str(user_id), **stats)

    async def _update_user_stats(
        self, guild_id: int, user_id: int, correct: bool
    ) -> None:
        stats = await self._get_user_stats(guild_id, user_id)
        if correct:
            stats["correct"] += 1
            stats["current_streak"] += 1
            if stats["current_streak"] > stats["best_streak"]:
                stats["best_streak"] = stats["current_streak"]
        else:
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

    def _queue_persist(
        self, guild_id: int, user_id: int, state: dict, correct: bool
    ) -> None:
        """Schreibt den bereits gefaellten Beschluss nach, ohne die naechste Zahl auszubremsen."""
        snapshot = {
            key: state.get(key) for key in ("last_number", "last_user_id", "highscore")
        }
        task = asyncio.create_task(self._persist(guild_id, user_id, snapshot, correct))
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    async def _persist(
        self, guild_id: int, user_id: int, snapshot: dict, correct: bool
    ) -> None:
        async with self._lock_for(self._write_locks, guild_id):
            try:
                await self.api.set_counting(str(guild_id), **snapshot)
                await self._update_user_stats(guild_id, user_id, correct)
            except Exception:
                logger.exception(
                    "Counting-Stand fuer Guild %s konnte nicht gespeichert werden",
                    guild_id,
                )

    async def _confirm_number(self, message: discord.Message) -> None:
        try:
            await message.add_reaction("✅")
        except Exception:
            logger.exception("Bestätigungs-Reaktion konnte nicht gesetzt werden")

    async def _announce_fail(self, message: discord.Message, reason: str) -> None:
        try:
            await message.reply(
                f"{message.author.mention} hat verkackt!\n"
                f"Grund: **{reason}**\n"
                "Der Zähler wurde zurückgesetzt, es startet wieder bei **1**.",
                mention_author=False,
            )
        except Exception:
            logger.exception("Fail-Meldung konnte nicht gesendet werden")

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

        # Der Reset muss auch laufende Bewertungen abwarten, sonst schreibt eine
        # Nachricht von eben den alten Stand direkt wieder zurueck.
        async with self._lock_for(self._eval_locks, guild.id):
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

        last = int(state.get("last_number") or 0)
        last_uid = state.get("last_user_id")
        highscore = int(state.get("highscore") or 0)
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
                f"**#{rank}** {name} – ✅ {e.get('correct', 0)} | Best-Streak: {e.get('best_streak', 0)}"
            )

        embed.add_field(
            name="Top 10 – Korrekte Zahlen", value="\n".join(lines), inline=False
        )
        await interaction.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if message.author.bot or not message.guild:
                return

            guild_id = message.guild.id
            # Erst der Cache, damit fremde Channels ohne await rausfallen: sonst
            # verschiebt schon diese Pruefung die Reihenfolge der Nachrichten.
            if guild_id in self._channel_cache:
                channel_id = self._channel_cache[guild_id]
            else:
                channel_id = await self._get_channel_id(guild_id)
            if channel_id is None or message.channel.id != channel_id:
                return

            # Ab hier ist der Lock die erste Wartestelle. Nachrichten werden damit
            # in Eingangsreihenfolge gewertet, statt sich ueber langsame DB-Calls
            # gegenseitig zu ueberholen.
            async with self._lock_for(self._eval_locks, guild_id):
                state = await self._get_state(guild_id)
                last_number = int(state.get("last_number") or 0)
                last_user_id = state.get("last_user_id")
                expected = last_number + 1

                number = _extract_counting_number(message.content.strip())
                if number is None:
                    reason = "Keine gültige Zahl"
                elif number <= 0:
                    reason = "Zahl muss positiv sein"
                elif last_user_id and int(last_user_id) == message.author.id:
                    reason = "Du darfst nicht zweimal hintereinander zählen"
                elif number != expected:
                    reason = "Falsche Zahl"
                else:
                    reason = None

                if reason is None:
                    state = self._apply_state(
                        state,
                        guild_id,
                        last_number=number,
                        last_user_id=message.author.id,
                        highscore=max(int(state.get("highscore") or 0), number),
                    )
                else:
                    state = self._apply_state(
                        state, guild_id, last_number=0, last_user_id=None
                    )
                self._queue_persist(
                    guild_id, message.author.id, state, correct=reason is None
                )

            # Discord-Antwort ausserhalb des Locks: die naechste Zahl wartet nicht
            # auf Reaktion oder Reply.
            if reason is None:
                await self._confirm_number(message)
            else:
                await self._announce_fail(message, reason)

        except Exception:
            logger.exception("Fehler im Counting-System")


async def setup(bot: commands.Bot):
    await bot.add_cog(CountingCog(bot))
