from __future__ import annotations

import os
import io
import re
from typing import Optional, Dict, Tuple

import aiohttp
import discord
from discord import ButtonStyle, app_commands
from discord.ext import commands

from src.pumbot.bot import logger
from src.pumbot.utils.datetime_format import format_berlin_datetime


TICKET_CATEGORY_NAME = "🎫 Tickets"
TICKET_LOG_CHANNEL_ID = 1441186559486595142
ADMIN_TICKET_ROLE_ID = 1510385400173039629

DISCORD_MOD_ROLES = {"Discord Moderator", "Discord Moderation"}
TWITCH_MOD_ROLES = {"Twitch Moderator", "Twitch Moderation"}
GENERAL_TICKET_ROLES = {"Admin", "Team", *DISCORD_MOD_ROLES, *TWITCH_MOD_ROLES}
TICKET_STAFF_ROLES = {*GENERAL_TICKET_ROLES, "Admin Ticket"}
TICKET_CATEGORY_STAFF_ROLES = {
    "discord": DISCORD_MOD_ROLES,
    "twitch": TWITCH_MOD_ROLES,
    "general": GENERAL_TICKET_ROLES,
    "admin": {"Admin Ticket"},
}


def is_ticket_staff(member: discord.Member) -> bool:
    try:
        if member.guild_permissions.administrator:
            return True
        return any(role.name in TICKET_STAFF_ROLES for role in member.roles)
    except Exception:
        logger.exception("is_ticket_staff error")
        return False


def format_dt(dt) -> str:
    try:
        return format_berlin_datetime(dt, fallback="Unbekannt")
    except Exception:
        logger.exception("format_dt error")
        return "Unbekannt"


async def create_transcript_text(channel: discord.TextChannel) -> str:
    try:
        buffer = io.StringIO()
        async for msg in channel.history(limit=None, oldest_first=True):
            timestamp = format_dt(msg.created_at)
            author = f"{msg.author} ({msg.author.id})"
            content = msg.content.replace("\n", "\\n") if msg.content else ""
            buffer.write(f"[{timestamp}] {author}: {content}\n")
        return buffer.getvalue()
    except Exception:
        logger.exception("create_transcript_text error")
        return ""


async def upload_transcript_to_mclogs(content: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.mclo.gs/1/log",
                data={"content": content},
            ) as resp:
                if resp.status < 200 or resp.status >= 300:
                    text = await resp.text()
                    raise RuntimeError(f"Fehler beim Upload zu mclo.gs: {resp.status} {text}")

                data = await resp.json()
                url = data.get("url")
                if not url and isinstance(data.get("data"), dict):
                    url = data["data"].get("url")

                if not url:
                    raise RuntimeError(f"Unerwartete Antwort von mclo.gs: {data}")

                return url
    except Exception:
        logger.exception("upload_transcript_to_mclogs error")
        raise


class TranscriptView(discord.ui.View):
    def __init__(self, url: str):
        super().__init__(timeout=None)
        try:
            self.add_item(
                discord.ui.Button(
                    label="Transkript öffnen",
                    style=ButtonStyle.link,
                    url=url,
                )
            )
        except Exception:
            logger.exception("TranscriptView init error")


class TicketSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.twitch_client_id: Optional[str] = os.getenv("TWITCH_CLIENT_ID")
        self.twitch_auth_token: Optional[str] = os.getenv("TWITCH_AUTH_TOKEN")
        self.session: Optional[aiohttp.ClientSession] = None

    async def cog_unload(self) -> None:
        try:
            if self.session and not self.session.closed:
                await self.session.close()
        except Exception:
            logger.exception("TicketSystemCog.cog_unload error")

    async def _get_twitch_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Save every message in a ticket channel to the DB via API."""
        try:
            if message.author.bot:
                return
            channel = message.channel
            if not isinstance(channel, discord.TextChannel):
                return
            if channel.category is None or channel.category.name != TICKET_CATEGORY_NAME:
                return

            content = message.content or ""
            if not content and message.attachments:
                content = " ".join(a.url for a in message.attachments)
            if not content:
                return

            await self.bot.api.add_ticket_message(
                ticket_id=str(channel.id),
                author_id=str(message.author.id),
                author_name=str(message.author),
                content=content,
                source="discord",
                discord_message_id=str(message.id),
            )
        except Exception:
            logger.exception("on_message ticket save error")

    async def validate_twitch_username(self, username: str) -> Tuple[bool, Optional[bool]]:
        try:
            username = username.strip().lower()
            if not username:
                return False, None

            if not (self.twitch_client_id and self.twitch_auth_token):
                logger.warning("validate_twitch_username: Twitch-API nicht konfiguriert, überspringe Check.")
                return True, None

            session = await self._get_twitch_session()
            url = "https://api.twitch.tv/helix/users"
            headers = {
                "Client-ID": self.twitch_client_id,
                "Authorization": f"Bearer {self.twitch_auth_token}",
            }
            params = {"login": username}

            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning("validate_twitch_username: HTTP %s – %s", resp.status, text)
                    return True, None

                data = await resp.json(content_type=None)
                users = data.get("data", [])
                exists = len(users) > 0
                if not exists:
                    return False, False
                return True, True
        except Exception:
            logger.exception("validate_twitch_username unexpected error")
            return True, None

    @staticmethod
    def _sanitize_channel_name(name: str) -> str:
        """Sanitize a string for use in a Discord channel name."""
        name = name.lower().replace(" ", "-")
        name = re.sub(r"[^a-z0-9\-_]", "", name)
        return name[:20].rstrip("-")

    async def create_ticket_channel(
        self,
        interaction: discord.Interaction,
        category_key: str,
        category_label: str,
        *,
        reason: str,
        twitch_name: Optional[str] = None,
        twitch_verified: Optional[bool] = None,
    ):
        try:
            guild = interaction.guild
            user = interaction.user

            if guild is None:
                await interaction.response.send_message("Tickets können nur auf einem Server erstellt werden.", ephemeral=True)
                return

            ticket_category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
            if ticket_category is None:
                ticket_category = await guild.create_category(TICKET_CATEGORY_NAME)

            safe_name = self._sanitize_channel_name(user.display_name)
            channel_name = f"ticket-{safe_name}-{category_key}"

            overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                ),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }

            allowed_role_names = TICKET_CATEGORY_STAFF_ROLES.get(
                category_key,
                TICKET_CATEGORY_STAFF_ROLES["general"],
            )
            for role in guild.roles:
                if category_key == "admin":
                    if role.id != ADMIN_TICKET_ROLE_ID:
                        continue
                elif role.name not in allowed_role_names:
                    continue
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

            topic_parts = [
                "TICKET",
                f"creator_id:{user.id}",
                f"creator_name:{user}",
                f"category:{category_key}",
                f"category_label:{category_label}",
                f"created_at:{discord.utils.utcnow().isoformat()}",
            ]
            if twitch_name:
                topic_parts.append(f"twitch_name:{twitch_name}")
                if twitch_verified is True:
                    topic_parts.append("twitch_verified:1")

            channel = await guild.create_text_channel(
                name=channel_name,
                category=ticket_category,
                overwrites=overwrites,
                topic="|".join(topic_parts) + "|",
            )

            # Register ticket in DB via API
            api = self.bot.api
            try:
                await api.upsert_ticket({
                    "ticket_id": str(channel.id),
                    "guild_id": str(guild.id),
                    "channel_id": str(channel.id),
                    "creator_user_id": str(user.id),
                    "creator_username": str(user),
                    "status": "open",
                    "subject": category_label,
                    "category": category_key,
                    "twitch_name": twitch_name,
                    "opened_at": discord.utils.utcnow().isoformat(),
                })
            except Exception:
                logger.exception("upsert_ticket (created) error")

            # Log creation via API
            try:
                await api.send_ticket_log(
                    ticket_id=str(channel.id),
                    user_name=str(user),
                    action="created",
                    content=f"{category_label} | Grund: {reason[:500]}",
                )
            except Exception:
                logger.exception("send_ticket_log created error")

            embed = discord.Embed(
                title=f"{category_label} – Ticket von {user}",
                description=(
                    "Ticket wurde erstellt.\n\n"
                    "Ein Teammitglied wird sich schnellstmöglich darum kümmern.\n\n"
                    "Zum Schließen des Tickets den Button unten verwenden."
                ),
                color=discord.Color.green(),
            )
            embed.add_field(name="Ersteller", value=f"{user.mention} (`{user.id}`)", inline=False)
            embed.add_field(name="Kategorie", value=category_label, inline=True)
            embed.add_field(name="Erstellt am", value=format_dt(discord.utils.utcnow()), inline=True)

            if twitch_name:
                tw_url = f"https://twitch.tv/{twitch_name}"
                base = f"[{twitch_name}]({tw_url})"
                if twitch_verified is True:
                    value = f"{base} ✅ (verifiziert)"
                elif twitch_verified is None:
                    value = f"{base} ⚠️ (nicht geprüft)"
                else:
                    value = base
                embed.add_field(name="Twitch-Name", value=value, inline=False)

            embed.add_field(name="Grund / Anliegen", value=reason[:1024], inline=False)

            view = TicketCloseView(self.bot)
            await channel.send(content=f"{user.mention}", embed=embed, view=view)

            await interaction.response.send_message(f"Dein Ticket wurde erstellt: {channel.mention}", ephemeral=True)
        except Exception:
            logger.exception("create_ticket_channel error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Fehler beim Erstellen des Tickets.", ephemeral=True)
                else:
                    await interaction.response.send_message("Fehler beim Erstellen des Tickets.", ephemeral=True)
            except Exception:
                logger.exception("create_ticket_channel followup error")

    async def close_ticket(
        self,
        closer: discord.Member,
        channel: discord.TextChannel,
        reason: Optional[str] = None,
    ):
        try:
            guild = channel.guild
            topic_data = self._parse_ticket_topic(channel.topic)
            creator_id = topic_data.get("creator_id")
            creator_name = topic_data.get("creator_name")
            category_label = topic_data.get("category")
            category_key = topic_data.get("category_key") or self._normalize_ticket_category(category_label)
            category_label = topic_data.get("category_label") or category_label
            created_at_iso = topic_data.get("created_at")
            twitch_name = topic_data.get("twitch_name")
            twitch_verified_flag = topic_data.get("twitch_verified")

            created_at_str = format_dt(created_at_iso)
            closed_at = discord.utils.utcnow()

            transcript_text = await create_transcript_text(channel)

            try:
                transcript_url = await upload_transcript_to_mclogs(transcript_text)
            except Exception:
                transcript_url = None

            api = self.bot.api

            # Log close action
            try:
                await api.send_ticket_log(
                    ticket_id=str(channel.id),
                    user_name=str(closer),
                    action="closed",
                    content=f"Grund: {reason or 'Per Button geschlossen.'} | Transcript: {transcript_url or 'kein Link'}",
                )
            except Exception:
                logger.exception("send_ticket_log closed error")

            # Archive ticket (updates DB + saves transcript HTML)
            try:
                await api.send_ticket_archive(
                    ticket_id=str(channel.id),
                    channel_name=channel.name,
                    category_label=category_label or "Unbekannt",
                    category=category_key or "general",
                    creator_id=str(creator_id) if creator_id else None,
                    creator_name=creator_name,
                    guild_id=str(guild.id),
                    opened_at=created_at_iso,
                    closed_at=closed_at.isoformat(),
                    closed_by_id=str(closer.id),
                    closed_by_name=str(closer),
                    close_reason=reason or "Per Button geschlossen.",
                    transcript_url=transcript_url,
                    transcript_text=transcript_text,
                )
            except Exception:
                logger.exception("send_ticket_archive error")

            log_channel = guild.get_channel(TICKET_LOG_CHANNEL_ID) if TICKET_LOG_CHANNEL_ID else None

            embed = discord.Embed(title="Ticket geschlossen", color=discord.Color.red())
            embed.add_field(name="Channel", value=f"{channel.name} (`{channel.id}`)", inline=False)

            if creator_id:
                embed.add_field(name="Ersteller", value=f"<@{creator_id}> (`{creator_id}`)", inline=False)

            embed.add_field(name="Geschlossen von", value=f"{closer.mention} (`{closer.id}`)", inline=False)

            if category_label:
                embed.add_field(name="Kategorie", value=category_label, inline=True)

            if twitch_name:
                tw_url = f"https://twitch.tv/{twitch_name}"
                base = f"[{twitch_name}]({tw_url})"
                if twitch_verified_flag == "1":
                    value = f"{base} ✅ (verifiziert)"
                elif twitch_verified_flag is None:
                    value = f"{base} ⚠️ (nicht geprüft)"
                else:
                    value = base
                embed.add_field(name="Twitch-Name", value=value, inline=True)

            embed.add_field(name="Erstellt am", value=created_at_str, inline=True)
            embed.add_field(name="Geschlossen am", value=format_dt(closed_at), inline=True)
            embed.add_field(name="Grund", value=reason or "Per Button geschlossen.", inline=False)

            view = TranscriptView(transcript_url) if transcript_url else None

            if log_channel is not None:
                await log_channel.send(embed=embed, view=view)
            else:
                await channel.send("Es ist kein Ticket-Log-Channel konfiguriert. Transcript-Link wird hier gesendet.")
                await channel.send(embed=embed, view=view)

            # ✅ DM an Ticket-Ersteller mit klickbarem Ticket-Link (Website oder Transcript)
            try:
                if creator_id:
                    creator_user = guild.get_member(int(creator_id)) or await self.bot.fetch_user(int(creator_id))

                    base = os.getenv("TICKET_VIEW_BASE_URL")  # z.B. http://127.0.0.1:3000/tickets
                    ticket_url = f"{base.rstrip('/')}/{channel.id}" if base else transcript_url
                    ticket_click = f"[{channel.name}]({ticket_url})" if ticket_url else channel.name

                    dm = discord.Embed(
                        title="🎫 Ticket geschlossen",
                        description="Hier sind die wichtigsten Infos zu deinem Ticket:",
                        color=discord.Color.red(),
                    )
                    dm.add_field(name="Ticket", value=f"{ticket_click} (`{channel.id}`)", inline=False)
                    dm.add_field(name="Tickettyp", value=category_label or "Unbekannt", inline=True)
                    dm.add_field(name="Geöffnet am", value=created_at_str, inline=True)
                    dm.add_field(name="Bearbeitet/Geschlossen von", value=f"{closer} (`{closer.id}`)", inline=False)
                    dm.add_field(name="Geschlossen am", value=format_dt(closed_at), inline=False)
                    dm.add_field(name="Grund", value=reason or "Per Button/Command geschlossen.", inline=False)
                    if transcript_url:
                        dm.add_field(name="Transcript", value=transcript_url, inline=False)

                    await creator_user.send(embed=dm)
            except discord.Forbidden:
                pass
            except Exception:
                logger.exception("DM creator failed")

            await channel.send("Dieses Ticket wird geschlossen.")
            await channel.delete(reason=reason or "Ticket geschlossen")
        except Exception:
            logger.exception("close_ticket error")
            try:
                await channel.send("Fehler beim Schließen des Tickets.")
            except Exception:
                logger.exception("close_ticket send error")

    @staticmethod
    def _parse_ticket_topic(topic: Optional[str]) -> Dict[str, str]:
        try:
            if not topic or not topic.startswith("TICKET|"):
                return {}

            data: Dict[str, str] = {}
            parts = topic.split("|")[1:]
            for part in parts:
                if ":" in part:
                    key, value = part.split(":", 1)
                    data[key] = value
            return data
        except Exception:
            logger.exception("_parse_ticket_topic error")
            return {}

    @staticmethod
    def _normalize_ticket_category(category: Optional[str]) -> str:
        value = (category or "").strip().lower()
        if "twitch" in value:
            return "twitch"
        if "discord" in value:
            return "discord"
        if "admin" in value:
            return "admin"
        return "general"

    ticket_group = app_commands.Group(
        name="ticket",
        description="Ticket-System Verwaltung.",
    )

    admin_group = app_commands.Group(
        name="admin",
        description="Admin-Funktionen.",
    )

    @ticket_group.command(name="panel", description="Erstellt ein Ticket-Panel für Benutzer-Anfragen.")
    async def ticket_panel(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return

        if not is_ticket_staff(interaction.user):
            await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Ticket-System",
            description=(
                "Bitte wähle eine Kategorie aus, um ein Ticket zu erstellen.\n"
                "Danach öffnet sich ein Fenster, in das du deinen Grund eintragen musst.\n\n"
                "📘 **Discord Support** – Hilfe rund um den Discord-Server\n"
                "💜 **Twitch Support** – Hilfe rund um deinen oder meinen Twitch-Stream\n"
                "📨 **Allgemeiner Support** – Sonstige Anliegen\n"
            ),
            color=discord.Color.blurple(),
        )

        view = TicketPanelView(self.bot)
        await interaction.response.send_message(embed=embed, view=view)

    @ticket_group.command(name="close", description="Schließt das aktuelle Ticket und erstellt ein Transcript (Staff).")
    @app_commands.describe(grund="Grund (optional)")
    async def close(self, interaction: discord.Interaction, grund: Optional[str] = None):
        channel = interaction.channel
        if interaction.guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Dieser Befehl kann nur in Ticket-Textchannels verwendet werden.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Konnte deine Mitgliedsdaten nicht lesen.", ephemeral=True)
            return

        if channel.category is None or channel.category.name != TICKET_CATEGORY_NAME:
            await interaction.response.send_message("Dieser Channel scheint kein Ticket-Channel zu sein.", ephemeral=True)
            return

        if not is_ticket_staff(member):
            await interaction.response.send_message("Du darfst dieses Ticket nicht schließen.", ephemeral=True)
            return

        await interaction.response.send_message("Ticket wird geschlossen …", ephemeral=True)
        await self.close_ticket(member, channel, reason=grund or "Per Slash Command geschlossen.")

    @admin_group.command(name="ticket", description="Erstellt ein Admin Ticket.")
    @app_commands.describe(grund="Grund / Anliegen")
    async def admin_ticket(self, interaction: discord.Interaction, grund: str):
        if interaction.guild is None:
            await interaction.response.send_message("Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True)
            return
        reason = (grund or "").strip()
        if not reason:
            await interaction.response.send_message("Bitte gib einen Grund an.", ephemeral=True)
            return
        await self.create_ticket_channel(
            interaction,
            category_key="admin",
            category_label="Admin Ticket",
            reason=reason,
            twitch_name=None,
        )

    @ticket_group.command(name="useradd", description="Fuegt einen User zu diesem Ticket hinzu (Staff).")
    @app_commands.describe(user="User")
    async def useradd(self, interaction: discord.Interaction, user: discord.Member):
        channel = interaction.channel
        if interaction.guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Dieser Befehl kann nur in Ticket-Textchannels verwendet werden.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Konnte deine Mitgliedsdaten nicht lesen.", ephemeral=True)
            return

        if channel.category is None or channel.category.name != TICKET_CATEGORY_NAME:
            await interaction.response.send_message("Dieser Channel ist kein Ticket-Channel.", ephemeral=True)
            return

        if not is_ticket_staff(member):
            await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
            return

        try:
            await channel.set_permissions(
                user,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                reason=f"User zu Ticket hinzugefügt durch {member} ({member.id})",
            )
        except discord.Forbidden:
            await interaction.response.send_message("Ich habe keine Rechte (Manage Channels), um User zu Tickets hinzuzufügen.", ephemeral=True)
            return
        except Exception:
            logger.exception("ticket useradd error")
            await interaction.response.send_message("Fehler beim Hinzufügen des Users zum Ticket.", ephemeral=True)
            return

        embed = discord.Embed(description=f"{user.mention} du wurdest dem Ticket hinzugefügt.", color=discord.Color.green())
        await channel.send(embed=embed)
        await interaction.response.send_message(f"{user.mention} wurde zum Ticket hinzugefügt.", ephemeral=True)

    @ticket_group.command(name="userremove", description="Entfernt einen User aus diesem Ticket (Staff).")
    @app_commands.describe(user="User")
    async def userremove(self, interaction: discord.Interaction, user: discord.Member):
        channel = interaction.channel
        if interaction.guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Dieser Befehl kann nur in Ticket-Textchannels verwendet werden.", ephemeral=True)
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Konnte deine Mitgliedsdaten nicht lesen.", ephemeral=True)
            return

        if channel.category is None or channel.category.name != TICKET_CATEGORY_NAME:
            await interaction.response.send_message("Dieser Channel ist kein Ticket-Channel.", ephemeral=True)
            return

        if not is_ticket_staff(member):
            await interaction.response.send_message("Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True)
            return

        try:
            await channel.set_permissions(
                user,
                overwrite=None,
                reason=f"User aus Ticket entfernt durch {member} ({member.id})",
            )
        except discord.Forbidden:
            await interaction.response.send_message("Ich habe keine Rechte (Manage Channels), um User zu Tickets zu entfernen.", ephemeral=True)
            return
        except Exception:
            logger.exception("ticket userremove error")
            await interaction.response.send_message("Fehler beim Entfernen des Users zum Ticket.", ephemeral=True)
            return

        embed = discord.Embed(description=f"{user.mention} du wurdest aus dem Ticket entfernt.", color=discord.Color.red())
        await channel.send(embed=embed)
        await interaction.response.send_message(f"{user.mention} wurde aus dem Ticket entfernt.", ephemeral=True)


class TicketReasonModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, category_key: str, category_label: str):
        super().__init__(title=f"{category_label} – Ticket erstellen")
        self.bot = bot
        self.category_key = category_key
        self.category_label = category_label

        self.reason_input = discord.ui.TextInput(
            label="Grund / Anliegen",
            placeholder="Beschreibe bitte kurz und klar dein Problem oder Anliegen.",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            reason = str(self.reason_input.value).strip()
            if not reason:
                await interaction.response.send_message("Bitte gib einen Grund / ein Anliegen an.", ephemeral=True)
                return

            cog = self.bot.get_cog("TicketSystemCog")
            if cog is None or not isinstance(cog, TicketSystemCog):
                await interaction.response.send_message("Ticket-System ist derzeit nicht verfügbar.", ephemeral=True)
                return

            await cog.create_ticket_channel(
                interaction,
                category_key=self.category_key,
                category_label=self.category_label,
                reason=reason,
                twitch_name=None,
            )
        except Exception:
            logger.exception("TicketReasonModal on_submit error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Fehler beim Erstellen des Tickets.", ephemeral=True)
                else:
                    await interaction.response.send_message("Fehler beim Erstellen des Tickets.", ephemeral=True)
            except Exception:
                logger.exception("TicketReasonModal followup error")


class TwitchTicketModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot):
        super().__init__(title="Twitch Support – Ticket erstellen")
        self.bot = bot

        self.twitch_name_input = discord.ui.TextInput(
            label="Dein Twitch-Name",
            placeholder="z.B. Pumpeklein",
            style=discord.TextStyle.short,
            required=True,
            max_length=50,
        )
        self.reason_input = discord.ui.TextInput(
            label="Grund / Anliegen",
            placeholder="Worum geht es genau?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
        )

        self.add_item(self.twitch_name_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            twitch_name = str(self.twitch_name_input.value).strip()
            reason = str(self.reason_input.value).strip()

            if not twitch_name:
                await interaction.response.send_message("Bitte gib deinen Twitch-Namen an.", ephemeral=True)
                return

            if not reason:
                await interaction.response.send_message("Bitte gib einen Grund / ein Anliegen an.", ephemeral=True)
                return

            cog = self.bot.get_cog("TicketSystemCog")
            if cog is None or not isinstance(cog, TicketSystemCog):
                await interaction.response.send_message("Ticket-System ist derzeit nicht verfügbar.", ephemeral=True)
                return

            proceed, exists_flag = await cog.validate_twitch_username(twitch_name)
            if not proceed:
                await interaction.response.send_message(
                    f"Der Twitch-Name **{twitch_name}** konnte auf Twitch nicht gefunden werden.\n"
                    "Bitte überprüfe die Schreibweise (genauer Login-Name) und versuche es erneut.",
                    ephemeral=True,
                )
                return

            await cog.create_ticket_channel(
                interaction,
                category_key="twitch",
                category_label="Twitch Support",
                reason=reason,
                twitch_name=twitch_name,
                twitch_verified=True if exists_flag is True else None,
            )
        except Exception:
            logger.exception("TwitchTicketModal on_submit error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Fehler beim Erstellen des Tickets.", ephemeral=True)
                else:
                    await interaction.response.send_message("Fehler beim Erstellen des Tickets.", ephemeral=True)
            except Exception:
                logger.exception("TwitchTicketModal followup error")


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _open_modal(self, interaction: discord.Interaction, key: str, label: str):
        try:
            if key == "twitch":
                modal = TwitchTicketModal(self.bot)
            else:
                modal = TicketReasonModal(self.bot, category_key=key, category_label=label)
            await interaction.response.send_modal(modal)
        except Exception:
            logger.exception("_open_modal error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Fehler beim Öffnen des Formulars.", ephemeral=True)
                else:
                    await interaction.response.send_message("Fehler beim Öffnen des Formulars.", ephemeral=True)
            except Exception:
                logger.exception("_open_modal followup error")

    @discord.ui.button(label="Discord Support", style=ButtonStyle.primary, emoji="📘", custom_id="ticket_panel_discord")
    async def discord_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, key="discord", label="Discord Support")

    @discord.ui.button(label="Twitch Support", style=ButtonStyle.primary, emoji="💜", custom_id="ticket_panel_twitch")
    async def twitch_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, key="twitch", label="Twitch Support")

    @discord.ui.button(label="Allgemeiner Support", style=ButtonStyle.secondary, emoji="📨", custom_id="ticket_panel_general")
    async def general_support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open_modal(interaction, key="general", label="Allgemeiner Support")


class TicketCloseReasonModal(discord.ui.Modal):
    """Modal for entering a custom close reason."""

    def __init__(self, bot: commands.Bot):
        super().__init__(title="Ticket schließen – Eigener Grund")
        self.bot = bot
        self.reason_input = discord.ui.TextInput(
            label="Grund",
            placeholder="Beschreibe den Grund für das Schließen …",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=500,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            reason = str(self.reason_input.value).strip() or "Kein Grund angegeben."
            channel = interaction.channel
            member = interaction.user
            if not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
                await interaction.response.send_message("Fehler.", ephemeral=True)
                return
            cog = self.bot.get_cog("TicketSystemCog")
            if cog is None or not isinstance(cog, TicketSystemCog):
                await interaction.response.send_message("Ticket-System ist derzeit nicht verfügbar.", ephemeral=True)
                return
            await interaction.response.send_message("Ticket wird geschlossen …", ephemeral=True)
            await cog.close_ticket(member, channel, reason=reason)
        except Exception:
            logger.exception("TicketCloseReasonModal on_submit error")


class TicketCloseReasonView(discord.ui.View):
    """View with a dropdown of predefined reasons + a custom reason button."""

    def __init__(self, bot: commands.Bot, reasons: list[dict]):
        super().__init__(timeout=120)
        self.bot = bot
        if reasons:
            options = [
                discord.SelectOption(label=r["label"][:100], value=r["label"][:100])
                for r in reasons[:25]
            ]
            self.reason_select = discord.ui.Select(
                placeholder="Grund auswählen …",
                options=options,
                custom_id="ticket_close_reason_select",
            )
            self.reason_select.callback = self._select_callback
            self.add_item(self.reason_select)

    async def _select_callback(self, interaction: discord.Interaction):
        try:
            reason = self.reason_select.values[0] if self.reason_select.values else "Kein Grund."
            channel = interaction.channel
            member = interaction.user
            if not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
                await interaction.response.send_message("Fehler.", ephemeral=True)
                return
            cog = self.bot.get_cog("TicketSystemCog")
            if cog is None or not isinstance(cog, TicketSystemCog):
                await interaction.response.send_message("Ticket-System nicht verfügbar.", ephemeral=True)
                return
            await interaction.response.send_message("Ticket wird geschlossen …", ephemeral=True)
            await cog.close_ticket(member, channel, reason=reason)
        except Exception:
            logger.exception("TicketCloseReasonView select_callback error")

    @discord.ui.button(label="Eigener Grund", style=ButtonStyle.secondary, emoji="✏️")
    async def custom_reason_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(TicketCloseReasonModal(self.bot))
        except Exception:
            logger.exception("custom_reason_button error")


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ticket schließen", style=ButtonStyle.danger, emoji="🔒", custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            channel = interaction.channel
            if not isinstance(channel, discord.TextChannel):
                await interaction.response.send_message("Dieser Button kann nur in Text-Channels verwendet werden.", ephemeral=True)
                return

            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message("Dieser Button kann nur auf einem Server verwendet werden.", ephemeral=True)
                return

            member = interaction.user
            if not isinstance(member, discord.Member):
                await interaction.response.send_message("Konnte deine Mitgliedsdaten nicht lesen.", ephemeral=True)
                return

            if not is_ticket_staff(member):
                await interaction.response.send_message("Du darfst dieses Ticket nicht schließen.", ephemeral=True)
                return

            # Fetch configurable close reasons from API
            reasons = []
            try:
                reasons = await self.bot.api.get_close_reasons(str(guild.id))
            except Exception:
                logger.exception("get_close_reasons error")

            if reasons:
                view = TicketCloseReasonView(self.bot, reasons)
                await interaction.response.send_message(
                    "Bitte wähle einen Grund aus oder gib einen eigenen ein:",
                    view=view,
                    ephemeral=True,
                )
            else:
                await interaction.response.send_modal(TicketCloseReasonModal(self.bot))
        except Exception:
            logger.exception("close_button error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Fehler beim Schließen des Tickets.", ephemeral=True)
                else:
                    await interaction.response.send_message("Fehler beim Schließen des Tickets.", ephemeral=True)
            except Exception:
                logger.exception("close_button followup error")


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketSystemCog(bot))
