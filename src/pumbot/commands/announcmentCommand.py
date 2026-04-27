from __future__ import annotations

import os
import json
import asyncio
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.pumbot.bot import logger
from src.pumbot.utils.datetime_format import format_berlin_datetime

ANNOUNCE_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}
TWITCH_PING_ROLE_ID = 1441253029432262787
TWITCH_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False,
    users=False,
    roles=[discord.Object(id=TWITCH_PING_ROLE_ID)],
    replied_user=False,
)
ANNOUNCE_ALLOWED_MENTIONS = discord.AllowedMentions(
    everyone=False,
    users=True,
    roles=True,
    replied_user=False,
)


def is_announce_staff(member: discord.Member) -> bool:
    try:
        if member.guild_permissions.administrator:
            return True
        return any(role.name in ANNOUNCE_STAFF_ROLES for role in member.roles)
    except Exception:
        logger.exception("is_announce_staff error")
        return False


def format_stream_times(started_at_str: str) -> tuple[str, str]:
    try:
        dt_utc = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)

        timestamp = int(dt_utc.timestamp())
        started_display = f"<t:{timestamp}:F>\n<t:{timestamp}:R>"
        delta = datetime.now(timezone.utc) - dt_utc.astimezone(timezone.utc)

        total_seconds = max(0, int(delta.total_seconds()))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60

        if hours > 0:
            duration_display = f"{hours} Std {minutes:02d} Min"
        else:
            duration_display = f"{minutes} Min"

        return started_display, duration_display
    except Exception:
        logger.exception("format_stream_times error")
        return format_berlin_datetime(started_at_str, fallback=started_at_str), "Unbekannt"


class AnnouncementCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api

        self.twitch_client_id = os.getenv("TWITCH_CLIENT_ID")
        self.twitch_auth_token = os.getenv("TWITCH_AUTH_TOKEN")
        self.twitch_user_login = os.getenv("TWITCH_USER_LOGIN")

        self.session: Optional[aiohttp.ClientSession] = None
        self.twitch_message_cache: Dict[int, int] = {}

        self.twitch_check_loop.start()

    def cog_unload(self) -> None:
        try:
            self.twitch_check_loop.cancel()
            if self.session and not self.session.closed:
                asyncio.create_task(self.session.close())
        except Exception:
            logger.exception("cog_unload error")

    async def get_session(self) -> aiohttp.ClientSession:
        try:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=15)
                self.session = aiohttp.ClientSession(timeout=timeout)
            return self.session
        except Exception:
            logger.exception("get_session error")
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
            return self.session

    async def get_twitch_announce_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        try:
            cfg = await self.api.get_twitch_config(str(guild.id))
            if not cfg:
                return None
            channel_id = cfg.get("channel_id")
            if not channel_id:
                return None
            chan = guild.get_channel(int(channel_id))
            return chan if isinstance(chan, discord.TextChannel) else None
        except Exception:
            logger.exception("get_twitch_announce_channel error")
            return None

    def twitch_ping_content(self) -> str:
        return f"<@&{TWITCH_PING_ROLE_ID}>"

    async def fetch_twitch_stream(self) -> List[Dict[str, Any]]:
        session = await self.get_session()
        url = "https://api.twitch.tv/helix/streams"

        headers = {
            "Client-ID": self.twitch_client_id or "",
            "Authorization": f"Bearer {self.twitch_auth_token or ''}",
        }
        params = {"user_login": self.twitch_user_login or ""}

        try:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logger.warning(
                        "[Twitch] HTTP %s: %s", resp.status, await resp.text()
                    )
                    return []
                data = await resp.json(content_type=None)
                return data.get("data", []) or []
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError):
            logger.exception("fetch_twitch_stream error")
            return []
        except Exception:
            logger.exception("fetch_twitch_stream unexpected error")
            return []

    async def fetch_twitch_game_name(self, game_id: str) -> Optional[str]:
        if not game_id:
            return None

        session = await self.get_session()
        url = "https://api.twitch.tv/helix/games"
        headers = {
            "Client-ID": self.twitch_client_id or "",
            "Authorization": f"Bearer {self.twitch_auth_token or ''}",
        }
        params = {"id": game_id}

        try:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                games = data.get("data", [])
                return games[0].get("name") if games else None
        except Exception:
            logger.exception("fetch_twitch_game_name error")
            return None

    async def send_or_update_twitch_announcement(
        self,
        channel: discord.TextChannel,
        stream: Dict[str, Any],
        *,
        force_new: bool = False,
    ) -> Optional[discord.Message]:
        embed = await self.build_twitch_embed(stream)
        cached_message_id = self.twitch_message_cache.get(channel.guild.id)

        if cached_message_id and not force_new:
            try:
                message = await channel.fetch_message(cached_message_id)
                await message.edit(embed=embed)
                return message
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                self.twitch_message_cache.pop(channel.guild.id, None)

        message = await channel.send(
            content=self.twitch_ping_content(),
            embed=embed,
            allowed_mentions=TWITCH_ALLOWED_MENTIONS,
        )
        self.twitch_message_cache[channel.guild.id] = message.id
        return message

    async def build_twitch_embed(self, stream: Dict[str, Any]) -> discord.Embed:
        try:
            title = stream.get("title") or "Live auf Twitch"
            game_name = await self.fetch_twitch_game_name(stream.get("game_id", ""))
            started_at = stream.get("started_at")

            thumb = (
                (stream.get("thumbnail_url") or "")
                .replace("{width}", "1920")
                .replace("{height}", "1080")
            )
            url = f"https://twitch.tv/{self.twitch_user_login}"

            embed = discord.Embed(
                title=f"{self.twitch_user_login} ist live auf Twitch!",
                description=f"**{title}**\n\n[Jetzt live zuschauen]({url})",
                color=discord.Color.purple(),
                url=url,
                timestamp=datetime.now(timezone.utc),
            )

            if game_name:
                embed.add_field(name="Game", value=game_name, inline=True)
            embed.add_field(name="Status", value="\U0001f534 **Live**", inline=True)

            if started_at:
                started_display, duration_display = format_stream_times(started_at)
                embed.add_field(name="Gestartet um", value=started_display, inline=True)
                embed.add_field(name="Dauer", value=duration_display, inline=True)

            if thumb:
                embed.set_image(url=thumb)

            embed.set_footer(text="Twitch Announcement")
            return embed
        except Exception:
            logger.exception("build_twitch_embed error")
            return discord.Embed(
                title=f"{self.twitch_user_login} ist live auf Twitch!",
                description="Stream ist live. Klicke hier zum Zuschauen.",
                color=discord.Color.purple(),
                url=f"https://twitch.tv/{self.twitch_user_login}",
            )

    twitch_announce_group = app_commands.Group(
        name="twitch_announce",
        description="Announcement- und Twitch-Settings.",
    )

    @app_commands.command(
        name="announce",
        description="Sendet eine sichtbare Ankündigung in diesen Channel.",
    )
    @app_commands.describe(text="Text der Ankündigung")
    async def announce(self, interaction: discord.Interaction, text: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_announce_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Ankündigung",
            description=text,
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_author(
            name=interaction.guild.name,
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        embed.set_footer(
            text=f"Gesendet von {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.send_message(
            embed=embed,
            allowed_mentions=ANNOUNCE_ALLOWED_MENTIONS,
        )

    @twitch_announce_group.command(
        name="channel",
        description="Setzt den Channel für Twitch-Live-Announcements.",
    )
    @app_commands.describe(channel="Textkanal")
    async def set_twitch_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_announce_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        await self.api.set_twitch_config(
            str(interaction.guild.id), channel_id=str(channel.id)
        )

        await interaction.response.send_message(
            f"Twitch-Announcement-Channel wurde auf {channel.mention} gesetzt.",
            ephemeral=True,
        )

    @twitch_announce_group.command(
        name="now",
        description="Sendet sofort einen Twitch-Live-Announcement, falls du live bist.",
    )
    async def twitch_announce_now(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_announce_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        if not all(
            [self.twitch_client_id, self.twitch_auth_token, self.twitch_user_login]
        ):
            await interaction.response.send_message(
                "Twitch API ist nicht korrekt konfiguriert (.env).", ephemeral=True
            )
            return

        streams = await self.fetch_twitch_stream()
        if not streams:
            await interaction.response.send_message(
                "Du scheinst aktuell nicht live zu sein.", ephemeral=True
            )
            return

        stream = streams[0]
        channel = await self.get_twitch_announce_channel(interaction.guild)
        if channel is None:
            await interaction.response.send_message(
                "Es ist kein Twitch-Announcement-Channel gesetzt.", ephemeral=True
            )
            return

        try:
            await self.send_or_update_twitch_announcement(
                channel, stream, force_new=True
            )
            stream_id = stream.get("id")
            if stream_id:
                await self.api.set_twitch_config(
                    str(interaction.guild.id), last_stream_id=stream_id
                )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "Ich konnte im Announcement-Channel nicht senden.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Twitch-Announcement wurde gesendet.", ephemeral=True
        )

    @tasks.loop(minutes=2)
    async def twitch_check_loop(self):
        await self.bot.wait_until_ready()
        if not all(
            [self.twitch_client_id, self.twitch_auth_token, self.twitch_user_login]
        ):
            return

        for guild in list(self.bot.guilds):
            try:
                g_id = str(guild.id)
                cfg = await self.api.get_twitch_config(g_id)
                if not cfg:
                    continue

                channel_id = cfg.get("channel_id")
                if not channel_id:
                    continue

                channel = guild.get_channel(int(channel_id))
                if not isinstance(channel, discord.TextChannel):
                    continue

                last_stream_id = cfg.get("last_stream_id")

                streams = await self.fetch_twitch_stream()
                if not streams:
                    self.twitch_message_cache.pop(guild.id, None)
                    continue

                stream = streams[0]
                stream_id = stream.get("id")

                if stream_id and stream_id != last_stream_id:
                    try:
                        await self.send_or_update_twitch_announcement(
                            channel, stream, force_new=True
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        logger.exception(
                            "Twitch announce send fehlgeschlagen (guild=%s)", guild.id
                        )

                    await self.api.set_twitch_config(g_id, last_stream_id=stream_id)
                elif stream_id and guild.id in self.twitch_message_cache:
                    try:
                        await self.send_or_update_twitch_announcement(channel, stream)
                    except (discord.Forbidden, discord.HTTPException):
                        logger.exception(
                            "Twitch announce update fehlgeschlagen (guild=%s)",
                            guild.id,
                        )

            except Exception:
                logger.exception("twitch_check_loop guild error (guild=%s)", guild.id)
                continue

    @twitch_check_loop.error
    async def twitch_check_loop_error(self, error: Exception):
        logger.exception("Fehler im twitch_check_loop: %r", error)


async def setup(bot: commands.Bot):
    await bot.add_cog(AnnouncementCog(bot))
