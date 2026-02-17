from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.mypackage import config
from src.mypackage.bot import logger


BASE_DIR = Path(__file__).resolve().parent.parent
LOG_CFG_FILE = BASE_DIR / "database" / "logs_config.json"

LOG_TYPES = ("voice", "user", "server", "message", "welcome")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_cfg() -> Dict[str, Any]:
    try:
        if not LOG_CFG_FILE.exists():
            return {"guilds": {}}
        with LOG_CFG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.exception("Fehler beim Laden der Logs-Config")
        return {"guilds": {}}


def _save_cfg(data: Dict[str, Any]) -> None:
    try:
        LOG_CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_CFG_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        logger.exception("Fehler beim Speichern der Logs-Config")


def _get_guild_cfg(guild_id: int) -> Dict[str, Any]:
    data = _load_cfg()
    return data.get("guilds", {}).get(str(guild_id), {})


def _set_guild_cfg(guild_id: int, cfg: Dict[str, Any]) -> None:
    data = _load_cfg()
    guilds = data.setdefault("guilds", {})
    guilds[str(guild_id)] = cfg
    _save_cfg(data)


def _set_log_channel(guild_id: int, log_type: str, channel_id: int) -> None:
    cfg = _get_guild_cfg(guild_id)
    channels = cfg.setdefault("channels", {})
    channels[log_type] = int(channel_id)
    cfg["channels"] = channels
    _set_guild_cfg(guild_id, cfg)


def _get_log_channel_id(guild_id: int, log_type: str) -> Optional[int]:
    cfg = _get_guild_cfg(guild_id)
    ch = cfg.get("channels", {}).get(log_type)
    return int(ch) if isinstance(ch, int) or (isinstance(ch, str) and str(ch).isdigit()) else None


def _staff_role_ids() -> set[int]:
    return set(getattr(config, "LOG_STAFF_ROLE_IDS", []) or [])


def _staff_role_names() -> set[str]:
    default = ["Admin", "Twitch Moderation", "Discord Moderation", "Team"]
    return set(getattr(config, "LOG_STAFF_ROLE_NAMES", default) or default)


def _is_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    ids = _staff_role_ids()
    if ids:
        return any(r.id in ids for r in member.roles)
    names = _staff_role_names()
    return any(r.name in names for r in member.roles)


async def _safe_fetch_channel(guild: discord.Guild, channel_id: int) -> Optional[discord.abc.Messageable]:
    ch = guild.get_channel(channel_id)
    if ch is not None:
        return ch
    try:
        return await guild.fetch_channel(channel_id)
    except Exception:
        return None


def _fmt_user(u: discord.abc.User) -> str:
    return f"{u.mention} (`{u.id}`)"


def _fmt_name_and_tag(u: discord.abc.User) -> str:
    try:
        return f"@{u.name} ({u.mention})"
    except Exception:
        return f"{u.mention}"


def _fmt_channel_label(ch: discord.abc.GuildChannel) -> str:
    if isinstance(ch, discord.TextChannel):
        return f"{ch.mention} (`{ch.name}`)"
    if hasattr(ch, "name"):
        return f"`{ch.name}`"
    return f"`{ch.id}`"


def _count_label(voice: discord.VoiceChannel) -> str:
    limit = voice.user_limit if voice.user_limit else "∞"
    return f"{len(voice.members)}/{limit}"


def _embed_base(title: str, color: discord.Color, thumb_url: Optional[str] = None) -> discord.Embed:
    e = discord.Embed(title=title, color=color, timestamp=_utcnow())
    if thumb_url:
        e.set_thumbnail(url=thumb_url)
    return e


def _kv_block(lines: list[tuple[str, str]]) -> str:
    out = []
    for k, v in lines:
        out.append(f"**{k}:** {v}")
    return "\n".join(out)


def _green() -> discord.Color:
    return discord.Color.green()


def _red() -> discord.Color:
    return discord.Color.red()


def _blue() -> discord.Color:
    return discord.Color.blurple()


def _yellow() -> discord.Color:
    return discord.Color.gold()


@dataclass
class AuditHint:
    action: Optional[discord.AuditLogAction] = None
    actor: Optional[discord.Member] = None


class LogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    logs = app_commands.Group(
        name="logs",
        description="Konfiguriere Log-Channels und Tests.",
    )

    def _check_staff(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        if not isinstance(interaction.user, discord.Member):
            return False
        return _is_staff(interaction.user)

    async def _send_log(self, guild: discord.Guild, log_type: str, embed: discord.Embed) -> None:
        channel_id = _get_log_channel_id(guild.id, log_type)
        if not channel_id:
            return
        channel = await _safe_fetch_channel(guild, channel_id)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except Exception:
            logger.exception("Konnte Log nicht senden (%s) in Guild %s", log_type, guild.id)

    async def _audit_hint_voice(self, guild: discord.Guild, target_id: int) -> AuditHint:
        try:
            async for entry in guild.audit_logs(limit=6):
                if entry.target is None or getattr(entry.target, "id", None) != target_id:
                    continue
                if entry.action in (discord.AuditLogAction.member_move, discord.AuditLogAction.member_disconnect):
                    if entry.created_at is None:
                        continue
                    age = (_utcnow() - entry.created_at.replace(tzinfo=timezone.utc)).total_seconds()
                    if age <= 15:
                        actor = entry.user if isinstance(entry.user, discord.Member) else None
                        return AuditHint(action=entry.action, actor=actor)
        except Exception:
            return AuditHint()
        return AuditHint()

    async def _lock_channel(self, channel: discord.TextChannel) -> Tuple[bool, str]:
        guild = channel.guild
        staff_names = _staff_role_names()
        staff_ids = _staff_role_ids()

        staff_roles = []
        for r in guild.roles:
            if staff_ids and r.id in staff_ids:
                staff_roles.append(r)
            elif (not staff_ids) and r.name in staff_names:
                staff_roles.append(r)

        if not staff_roles:
            return False, "Keine passenden Staff-Rollen gefunden."

        overwrites = channel.overwrites
        overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)

        for role in staff_roles:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True)

        me = guild.me
        if me is not None:
            overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True)

        try:
            await channel.edit(overwrites=overwrites)
            return True, "Channel-Rechte gesetzt."
        except discord.Forbidden:
            return False, "Mir fehlt die Berechtigung 'Kanäle verwalten'."
        except Exception:
            logger.exception("Fehler beim Setzen der Channel-Overwrites")
            return False, "Unbekannter Fehler beim Setzen der Rechte."

    @logs.command(name="set", description="Setzt einen Log-Channel (voice/user/server/message/welcome).")
    @app_commands.describe(
        log_type="voice/user/server/message/welcome",
        channel="Channel, in den geloggt werden soll",
        lock="Wenn true: Bot setzt Channel-Rechte so, dass nur Staff es sehen kann",
    )
    async def logs_set(
        self,
        interaction: discord.Interaction,
        log_type: str,
        channel: discord.TextChannel,
        lock: Optional[bool] = False,
    ) -> None:
        if not self._check_staff(interaction):
            await interaction.response.send_message("Dafür hast du keine Berechtigung.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        log_type = log_type.lower().strip()
        if log_type not in LOG_TYPES:
            await interaction.response.send_message(
                "Ungültiger Typ. Erlaubt: voice, user, server, message, welcome",
                ephemeral=True,
            )
            return

        _set_log_channel(guild.id, log_type, channel.id)

        msg = f"{log_type}-Log Channel gesetzt: {channel.mention}"
        if lock:
            _, detail = await self._lock_channel(channel)
            msg = f"{msg}\n{detail}"

        await interaction.response.send_message(msg, ephemeral=True)

    @logs.command(name="show", description="Zeigt die aktuell gesetzten Log-Channels.")
    async def logs_show(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        cfg = _get_guild_cfg(guild.id).get("channels", {})
        lines = []
        for t in LOG_TYPES:
            cid = cfg.get(t)
            if cid:
                ch = guild.get_channel(int(cid))
                lines.append(f"- **{t}**: {ch.mention if ch else f'`{cid}`'}")
            else:
                lines.append(f"- **{t}**: —")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @logs.command(name="test", description="Sendet einen Test-Log in den gewünschten Typ.")
    @app_commands.describe(log_type="voice/user/server/message/welcome")
    async def logs_test(self, interaction: discord.Interaction, log_type: str) -> None:
        if not self._check_staff(interaction):
            await interaction.response.send_message("Dafür hast du keine Berechtigung.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Nur auf einem Server nutzbar.", ephemeral=True)
            return

        log_type = log_type.lower().strip()
        if log_type not in LOG_TYPES:
            await interaction.response.send_message(
                "Ungültiger Typ. Erlaubt: voice, user, server, message, welcome",
                ephemeral=True,
            )
            return

        thumb = interaction.user.display_avatar.url if interaction.user else None
        embed = _embed_base("Test Log", _blue(), thumb_url=thumb)
        embed.description = _kv_block([("Type", log_type)])
        await self._send_log(guild, log_type, embed)
        await interaction.response.send_message("Test gesendet.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return

        embed = _embed_base("User joined", _green(), thumb_url=member.display_avatar.url)
        created = f"<t:{int(member.created_at.replace(tzinfo=timezone.utc).timestamp())}:R>"
        embed.description = _kv_block(
            [
                ("User", _fmt_name_and_tag(member)),
                ("ID", str(member.id)),
                ("Created", created),
                ("Members", str(member.guild.member_count or "—")),
            ]
        )
        await self._send_log(member.guild, "welcome", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.guild is None:
            return

        joined = "—"
        if member.joined_at:
            joined = f"<t:{int(member.joined_at.replace(tzinfo=timezone.utc).timestamp())}:R>"

        roles = [r.mention for r in getattr(member, "roles", []) if r.name != "@everyone"]
        roles_text = " → ".join(roles) if roles else "—"

        embed = _embed_base("User left", _red(), thumb_url=member.display_avatar.url)
        embed.description = _kv_block(
            [
                ("User", _fmt_name_and_tag(member)),
                ("ID", str(member.id)),
                ("Joined", joined),
                ("Roles", roles_text),
                ("Members", str(member.guild.member_count or "—")),
            ]
        )
        await self._send_log(member.guild, "welcome", embed)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        guild = member.guild
        if guild is None or member.bot:
            return

        bch = before.channel
        ach = after.channel

        if bch is None and ach is None:
            return

        if bch is None and ach is not None:
            embed = _embed_base("User joined channel", _green(), thumb_url=member.display_avatar.url)
            embed.description = _kv_block(
                [
                    ("User", _fmt_name_and_tag(member)),
                    ("Channel", _fmt_channel_label(ach)),
                    ("Users", _count_label(ach)),
                ]
            )
            await self._send_log(guild, "voice", embed)
            return

        if bch is not None and ach is None:
            hint = await self._audit_hint_voice(guild, member.id)
            color = _red()
            title = "User left channel"

            if hint.action == discord.AuditLogAction.member_disconnect:
                title = "User left channel"
                color = _red()

            embed = _embed_base(title, color, thumb_url=member.display_avatar.url)
            lines = [
                ("User", _fmt_name_and_tag(member)),
                ("Channel", _fmt_channel_label(bch)),
                ("Users", _count_label(bch)),
            ]
            if hint.actor:
                lines.append(("By", _fmt_name_and_tag(hint.actor)))
            embed.description = _kv_block(lines)
            await self._send_log(guild, "voice", embed)
            return

        if bch is not None and ach is not None and bch.id != ach.id:
            hint = await self._audit_hint_voice(guild, member.id)

            embed = _embed_base("User switched channel", _blue(), thumb_url=member.display_avatar.url)
            lines = [
                ("User", _fmt_name_and_tag(member)),
                ("Channel", _fmt_channel_label(ach)),
                ("Users", _count_label(ach)),
                ("Previous channel", _fmt_channel_label(bch)),
                ("Previous users", _count_label(bch)),
            ]
            if hint.action == discord.AuditLogAction.member_move and hint.actor:
                lines.append(("Moved by", _fmt_name_and_tag(hint.actor)))
            embed.description = _kv_block(lines)

            await self._send_log(guild, "voice", embed)
            return

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild
        if guild is None or after.bot:
            return

        blocks = []

        if before.nick != after.nick:
            blocks.append(
                ("User nick update", [("User", _fmt_name_and_tag(after)), ("Before", before.nick or "—"), ("After", after.nick or "—")], _yellow())
            )

        if before.roles != after.roles:
            before_set = {r.id for r in before.roles}
            after_set = {r.id for r in after.roles}
            added = [r.mention for r in after.roles if r.id not in before_set and r.name != "@everyone"]
            removed = [r.mention for r in before.roles if r.id not in after_set and r.name != "@everyone"]

            if added or removed:
                lines = [("User", _fmt_name_and_tag(after))]
                if added:
                    lines.append(("Added", " → ".join(added)))
                    color = _green()
                    title = "User roles added"
                else:
                    color = _red()
                    title = "User roles removed"
                if removed:
                    lines.append(("Removed", " → ".join(removed)))
                    title = "User roles update"
                    color = _yellow()
                blocks.append((title, lines, color))

        if not blocks:
            return

        for title, lines, col in blocks[:3]:
            embed = _embed_base(title, col, thumb_url=after.display_avatar.url)
            embed.description = _kv_block(lines)
            await self._send_log(guild, "user", embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        changes = []
        if before.name != after.name:
            changes.append(("Name", before.name, after.name))
        if before.owner_id != after.owner_id:
            changes.append(("Owner", str(before.owner_id), str(after.owner_id)))
        if before.icon != after.icon:
            changes.append(("Icon", "changed", "changed"))

        if not changes:
            return

        embed = _embed_base("Server updated", _blue(), thumb_url=after.icon.url if after.icon else None)
        lines = [("Server", f"{after.name} (`{after.id}`)")]
        for n, b, a in changes:
            lines.append((n, f"{b} → {a}"))
        embed.description = _kv_block(lines)
        await self._send_log(after, "server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        embed = _embed_base("Channel created", _green())
        embed.description = _kv_block(
            [
                ("Channel", f"{_fmt_channel_label(channel)}"),
                ("Type", channel.type.name),
                ("ID", str(channel.id)),
            ]
        )
        await self._send_log(channel.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        embed = _embed_base("Channel deleted", _red())
        embed.description = _kv_block(
            [
                ("Channel", f"`{channel.name}`"),
                ("Type", channel.type.name),
                ("ID", str(channel.id)),
            ]
        )
        await self._send_log(channel.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        changes = []
        if before.name != after.name:
            changes.append(("Name", before.name, after.name))

        if hasattr(before, "topic") and hasattr(after, "topic"):
            if getattr(before, "topic", None) != getattr(after, "topic", None):
                changes.append(("Topic", getattr(before, "topic", None) or "—", getattr(after, "topic", None) or "—"))

        if not changes:
            return

        embed = _embed_base("Channel updated", _blue())
        lines = [
            ("Channel", _fmt_channel_label(after)),
            ("ID", str(after.id)),
        ]
        for n, b, a in changes:
            lines.append((n, f"{b} → {a}"))
        embed.description = _kv_block(lines)
        await self._send_log(after.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = _embed_base("Role created", _green())
        embed.description = _kv_block([("Role", role.mention), ("ID", str(role.id))])
        await self._send_log(role.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = _embed_base("Role deleted", _red())
        embed.description = _kv_block([("Role", f"`{role.name}`"), ("ID", str(role.id))])
        await self._send_log(role.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        changes = []
        if before.name != after.name:
            changes.append(("Name", before.name, after.name))
        if before.color != after.color:
            changes.append(("Color", str(before.color), str(after.color)))
        if before.permissions.value != after.permissions.value:
            changes.append(("Permissions", "changed", "changed"))

        if not changes:
            return

        embed = _embed_base("Role updated", _yellow())
        lines = [("Role", after.mention), ("ID", str(after.id))]
        for n, b, a in changes:
            lines.append((n, f"{b} → {a}"))
        embed.description = _kv_block(lines)
        await self._send_log(after.guild, "server", embed)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        if message.author is None or message.author.bot:
            return

        embed = _embed_base("Message deleted", _red(), thumb_url=message.author.display_avatar.url)
        created = "—"
        if message.created_at:
            created = f"<t:{int(message.created_at.replace(tzinfo=timezone.utc).timestamp())}:R>"

        lines = [
            ("Channel", f"{message.channel.mention if hasattr(message.channel, 'mention') else f'`{message.channel.id}`'}"),
            ("Message ID", str(message.id)),
            ("Message author", _fmt_name_and_tag(message.author)),
            ("Message created", created),
        ]
        embed.description = _kv_block(lines)

        content = (message.content or "").strip()
        if content:
            if len(content) > 900:
                content = content[:900] + "…"
            embed.add_field(name="Content", value=f"```{content}```", inline=False)

        if message.attachments:
            urls = "\n".join(a.url for a in message.attachments)
            if len(urls) > 1000:
                urls = urls[:1000] + "…"
            embed.add_field(name="Attachments", value=urls, inline=False)

        await self._send_log(message.guild, "message", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if after.guild is None:
            return
        if after.author is None or after.author.bot:
            return
        if before.content == after.content:
            return

        embed = _embed_base("Message edited", _yellow(), thumb_url=after.author.display_avatar.url)
        created = "—"
        if after.created_at:
            created = f"<t:{int(after.created_at.replace(tzinfo=timezone.utc).timestamp())}:R>"

        lines = [
            ("Channel", f"{after.channel.mention if hasattr(after.channel, 'mention') else f'`{after.channel.id}`'}"),
            ("Message ID", str(after.id)),
            ("Message author", _fmt_name_and_tag(after.author)),
            ("Message created", created),
        ]
        embed.description = _kv_block(lines)

        b = (before.content or "").strip()
        a = (after.content or "").strip()

        if len(b) > 900:
            b = b[:900] + "…"
        if len(a) > 900:
            a = a[:900] + "…"

        if b:
            embed.add_field(name="Before", value=f"```{b}```", inline=True)
        else:
            embed.add_field(name="Before", value="``` ```", inline=True)

        if a:
            embed.add_field(name="After", value=f"```{a}```", inline=True)
        else:
            embed.add_field(name="After", value="``` ```", inline=True)

        embed.add_field(name="Jump", value=f"{after.jump_url}", inline=False)

        await self._send_log(after.guild, "message", embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LogsCog(bot))
