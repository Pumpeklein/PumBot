from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger

SELFROLE_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}
SELFROLE_CHANNEL_CONFIG_KEY = "selfrole_channel_id"

# Discord erlaubt maximal 25 Optionen pro Select-Menü.
MAX_ROLES_PER_PANEL = 25
# So lange gilt eine gerade angewandte Rollenänderung als Wahrheit, auch wenn
# der Member-Cache das GUILD_MEMBER_UPDATE noch nicht gesehen hat.
ROLE_STATE_TTL_SECONDS = 30.0

NO_PING = discord.AllowedMentions.none()

EMOJI_PREFIX_RE = re.compile(
    r"^\s*("
    r"<a?:[A-Za-z0-9_]+:\d+>"
    r"|[\U0001F1E6-\U0001F1FF]{2}"  # Flaggen bestehen aus zwei Zeichen
    r"|[0-9#*]️?⃣"
    r"|(?:[\U0001F000-\U0001FAFF←-⇿☀-➿⤀-⥿⬀-⯿]"
    r"[︎️]?(?:‍[\U0001F000-\U0001FAFF☀-➿][︎️]?)*)"
    r")\s*"
)

# Findet sich kein sinnvolles Emoji, bekommt die Rolle gar keins. Die Spalte
# `emoji` ist zusammen mit dem Panel eindeutig, deshalb braucht auch "kein
# Emoji" pro Rolle einen eigenen, unsichtbaren Wert.
NO_EMOJI_MARKER = "⁣"

# Aus der ersten Version: sinnlose Farbklekse, die beim nächsten Deploy durch
# ein echtes Emoji ersetzt werden dürfen.
LEGACY_FALLBACK_EMOJIS = {
    "🔹", "🔸", "🔶", "🔷", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤",
    "⚪", "⚫", "🟥", "🟧", "🟨", "🟩", "🟦", "🟪", "⭐", "✨",
    "💠", "🔘", "◽", "◾", "🔺",
}

NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def is_selfrole_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name in SELFROLE_STAFF_ROLES for r in member.roles)


def split_emoji(text: str) -> Tuple[Optional[str], str]:
    """Trennt ein führendes Emoji vom Rest des Namens."""
    match = EMOJI_PREFIX_RE.match(text or "")
    if not match:
        return None, (text or "").strip()
    return match.group(1), (text or "")[match.end():].strip()


def role_display_name(role: discord.Role) -> str:
    """Rollenname ohne führendes Emoji – das steht im Menü schon separat."""
    _, rest = split_emoji(role.name)
    return rest or role.name


def placeholder_emoji(role_id: int) -> str:
    return f"{NO_EMOJI_MARKER}{role_id}"


def is_no_emoji(emoji: Optional[str]) -> bool:
    return not emoji or emoji.startswith(NO_EMOJI_MARKER)


def keepable_emoji(emoji: Optional[str]) -> bool:
    """Ein bewusst gesetztes oder sinnvoll erkanntes Emoji bleibt erhalten."""
    return bool(emoji) and not is_no_emoji(emoji) and emoji not in LEGACY_FALLBACK_EMOJIS


def display_emoji(emoji: Optional[str]) -> Optional[str]:
    return None if is_no_emoji(emoji) else emoji


def normalize(text: str) -> str:
    return NORMALIZE_RE.sub("", (text or "").lower())


def guild_emoji_for(guild: discord.Guild, role: discord.Role) -> Optional[str]:
    """Sucht ein Server-Emoji, dessen Name zur Rolle passt (z. B. :valorant:)."""
    target = normalize(role_display_name(role))
    if len(target) < 3:
        return None

    partial: Optional[str] = None
    for emoji in getattr(guild, "emojis", []):
        name = normalize(emoji.name)
        if not name:
            continue
        if name == target:
            return str(emoji)
        if partial is None and len(name) >= 4 and (name in target or target in name):
            partial = str(emoji)
    return partial


def auto_emoji(guild: discord.Guild, role: discord.Role, used: Set[str]) -> Optional[str]:
    """Kaskade: Rollen-Icon → Emoji im Rollennamen → passendes Server-Emoji."""
    for candidate in (
        role.unicode_emoji,
        split_emoji(role.name)[0],
        guild_emoji_for(guild, role),
    ):
        if candidate and candidate not in used:
            return candidate
    return None


def role_blocker(guild: discord.Guild, role: discord.Role) -> Optional[str]:
    """Grund, warum der Bot diese Rolle nicht vergeben kann, sonst None."""
    if role == guild.default_role:
        return "die `@everyone` Rolle kann nicht vergeben werden"
    if role.managed:
        return "die Rolle wird von einer Integration verwaltet"
    me = guild.me
    if me is None:
        return "ich bin auf diesem Server nicht als Mitglied geladen"
    if not me.guild_permissions.manage_roles:
        return "mir fehlt die Berechtigung „Rollen verwalten“"
    if role >= me.top_role:
        return "die Rolle steht über meiner höchsten Rolle"
    return None


def panel_max_roles(panel: Dict[str, Any]) -> int:
    try:
        return max(0, int(panel.get("max_roles") or 0))
    except (TypeError, ValueError):
        return 0


def panel_title_parts(panel: Dict[str, Any]) -> Tuple[Optional[str], str]:
    emoji, rest = split_emoji(str(panel.get("title") or "Rollen"))
    return emoji, rest or "Rollen"


class PanelEntry:
    """Eine Zeile eines Panels: Emoji + aufgelöste Rolle."""

    __slots__ = ("emoji", "role")

    def __init__(self, emoji: str, role: discord.Role):
        self.emoji = emoji
        self.role = role


def resolve_entries(guild: discord.Guild, panel: Dict[str, Any]) -> List[PanelEntry]:
    entries: List[PanelEntry] = []
    seen_roles: Set[int] = set()
    for emoji, role_id in (panel.get("roles") or {}).items():
        try:
            role = guild.get_role(int(role_id))
        except (TypeError, ValueError):
            continue
        if role is None or role.id in seen_roles:
            continue
        seen_roles.add(role.id)
        entries.append(PanelEntry(str(emoji), role))
    return entries[:MAX_ROLES_PER_PANEL]


def build_entries(
    guild: discord.Guild,
    roles: Sequence[discord.Role],
    preset: Optional[Dict[int, str]] = None,
) -> List[PanelEntry]:
    """Baut die Emoji/Rollen-Liste. Gesetzte Emojis aus `preset` bleiben stehen."""
    preset = preset or {}
    used: Set[str] = {e for e in preset.values() if keepable_emoji(e)}

    entries: List[PanelEntry] = []
    for role in roles:
        emoji = preset.get(role.id)
        if not keepable_emoji(emoji):
            emoji = auto_emoji(guild, role, used)
        if emoji:
            used.add(emoji)
        entries.append(PanelEntry(emoji or placeholder_emoji(role.id), role))
    return entries


def role_chip(entry: PanelEntry) -> str:
    emoji = display_emoji(entry.emoji)
    name = f"`{role_display_name(entry.role)}`"
    return f"{emoji} {name}" if emoji else name


def render_panel_message(panel: Dict[str, Any], entries: List[PanelEntry]) -> str:
    emoji, title = panel_title_parts(panel)
    header = f"## {emoji + ' ' if emoji else ''}{title}"

    if not entries:
        return f"{header}\n-# Für diese Kategorie sind noch keine Rollen hinterlegt."

    lines = [header, " · ".join(role_chip(entry) for entry in entries)]

    max_roles = panel_max_roles(panel)
    if max_roles == 1:
        lines.append("-# Du kannst hier genau eine Rolle wählen.")
    elif max_roles > 1:
        lines.append(f"-# Du kannst hier bis zu {max_roles} Rollen wählen.")

    return "\n".join(lines)


class SelfRoleSelect(discord.ui.Select):
    def __init__(self, cog: "SelfRolesCog", panel: Dict[str, Any], entries: List[PanelEntry], held: Set[int]):
        self.cog = cog
        self.panel = panel
        self.entries = entries

        max_roles = panel_max_roles(panel)
        options = [
            discord.SelectOption(
                label=role_display_name(entry.role)[:100],
                value=str(entry.role.id),
                emoji=display_emoji(entry.emoji),
                default=entry.role.id in held,
            )
            for entry in entries
        ]

        limit = len(options) if max_roles == 0 else min(max_roles, len(options))
        super().__init__(
            placeholder="Rollen auswählen …" if max_roles != 1 else "Rolle auswählen …",
            min_values=0,
            max_values=max(1, limit),
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = {int(value) for value in self.values}
        await self.cog.apply_selection(interaction, self.panel, self.entries, selected)


class SelfRoleClearButton(discord.ui.Button):
    def __init__(self, cog: "SelfRolesCog", panel: Dict[str, Any], entries: List[PanelEntry]):
        super().__init__(label="Alle entfernen", style=discord.ButtonStyle.danger, emoji="🗑️")
        self.cog = cog
        self.panel = panel
        self.entries = entries

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.apply_selection(interaction, self.panel, self.entries, set())


class SelfRoleChooserView(discord.ui.View):
    """Ephemere Auswahl, die nur für einen Klick lebt."""

    def __init__(self, cog: "SelfRolesCog", panel: Dict[str, Any], entries: List[PanelEntry], held: Set[int]):
        super().__init__(timeout=180)
        if entries:
            self.add_item(SelfRoleSelect(cog, panel, entries, held))
            self.add_item(SelfRoleClearButton(cog, panel, entries))


class SelfRoleOpenButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"selfroles:open:(?P<panel_id>\d+)",
):
    """Bleibt über Neustarts hinweg klickbar, weil die Panel-ID in der custom_id steht."""

    def __init__(self, panel_id: int, label: str = "Rollen wählen", emoji: Optional[str] = None):
        self.panel_id = panel_id
        super().__init__(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.primary,
                emoji=emoji,
                custom_id=f"selfroles:open:{panel_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["panel_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("SelfRolesCog")
        if cog is None:
            await interaction.response.send_message(
                "Das Rollensystem ist gerade nicht verfügbar.", ephemeral=True
            )
            return
        await cog.open_chooser(interaction, self.panel_id)


def panel_view(panel: Dict[str, Any]) -> discord.ui.View:
    emoji, _ = panel_title_parts(panel)
    view = discord.ui.View(timeout=None)
    view.add_item(SelfRoleOpenButton(int(panel["id"]), emoji=emoji))
    return view


class SelfRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        # (guild_id, member_id) -> {role_id: (hat_rolle, timestamp)}
        self._pending_roles: Dict[Tuple[int, int], Dict[int, Tuple[bool, float]]] = {}
        self._member_locks: Dict[Tuple[int, int], asyncio.Lock] = {}
        self._deploy_locks: Dict[int, asyncio.Lock] = {}
        self._startup_synced: Set[int] = set()

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(SelfRoleOpenButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(SelfRoleOpenButton)

    # ── Rollenzustand ──

    def _member_lock(self, guild_id: int, member_id: int) -> asyncio.Lock:
        return self._member_locks.setdefault((guild_id, member_id), asyncio.Lock())

    def _remember_role_state(
        self, guild_id: int, member_id: int, role_ids: Iterable[int], has_role: bool
    ) -> None:
        state = self._pending_roles.setdefault((guild_id, member_id), {})
        now = time.monotonic()
        for role_id in role_ids:
            state[role_id] = (has_role, now)

    def held_panel_roles(self, member: discord.Member, panel_role_ids: Set[int]) -> Set[int]:
        """Rollen aus diesem Panel, die der Member hat.

        Der Member-Cache hinkt hinter unseren eigenen Änderungen her, weil
        Discord die Rollen erst per Gateway-Event zurückmeldet. Ohne das Overlay
        zeigt ein zweiter Klick direkt danach noch den alten Stand.
        """
        held = {role.id for role in member.roles if role.id in panel_role_ids}

        key = (member.guild.id, member.id)
        state = self._pending_roles.get(key)
        if not state:
            return held

        now = time.monotonic()
        for role_id, (has_role, changed_at) in list(state.items()):
            if now - changed_at > ROLE_STATE_TTL_SECONDS:
                state.pop(role_id, None)
                continue
            if role_id not in panel_role_ids:
                continue
            if has_role:
                held.add(role_id)
            else:
                held.discard(role_id)

        if not state:
            self._pending_roles.pop(key, None)
        return held

    # ── Interaktionen ──

    async def open_chooser(self, interaction: discord.Interaction, panel_id: int) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Das geht nur auf einem Server.", ephemeral=True
            )
            return

        panel = await self.api.get_selfrole_panel_by_id(panel_id)
        if not panel:
            await interaction.response.send_message(
                "Diese Rollen-Kategorie gibt es nicht mehr.", ephemeral=True
            )
            return

        entries = resolve_entries(guild, panel)
        if not entries:
            await interaction.response.send_message(
                "Für diese Kategorie sind aktuell keine Rollen hinterlegt.", ephemeral=True
            )
            return

        held = self.held_panel_roles(member, {entry.role.id for entry in entries})
        await interaction.response.send_message(
            content=self._chooser_text(panel, entries, held),
            view=SelfRoleChooserView(self, panel, entries, held),
            ephemeral=True,
            allowed_mentions=NO_PING,
        )

    def _chooser_text(
        self, panel: Dict[str, Any], entries: List[PanelEntry], held: Set[int]
    ) -> str:
        emoji, title = panel_title_parts(panel)
        active = [entry for entry in entries if entry.role.id in held]
        active_text = (
            " · ".join(role_chip(entry) for entry in active) if active else "*keine*"
        )
        hint = (
            "Deine Auswahl ersetzt die bisherige Rolle aus dieser Kategorie."
            if panel_max_roles(panel) == 1
            else "Deine Auswahl ist der neue Endzustand – abgewählte Rollen werden entfernt."
        )
        return (
            f"### {emoji + ' ' if emoji else ''}{title}\n"
            f"Aktiv: {active_text}\n"
            f"-# {hint}"
        )

    async def apply_selection(
        self,
        interaction: discord.Interaction,
        panel: Dict[str, Any],
        entries: List[PanelEntry],
        selected: Set[int],
    ) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        await interaction.response.defer(ephemeral=True)

        panel_role_ids = {entry.role.id for entry in entries}
        by_id = {entry.role.id: entry for entry in entries}

        async with self._member_lock(guild.id, member.id):
            held = self.held_panel_roles(member, panel_role_ids)

            to_add = [by_id[rid].role for rid in selected - held if rid in by_id]
            to_remove = [by_id[rid].role for rid in held - selected if rid in by_id]

            blocked: List[str] = []
            addable: List[discord.Role] = []
            for role in to_add:
                blocker = role_blocker(guild, role)
                if blocker is None:
                    addable.append(role)
                else:
                    blocked.append(f"**{role_display_name(role)}** ({blocker})")
                    logger.warning(
                        "Self-Role: %s kann nicht vergeben werden (%s). Panel %s, Guild %s.",
                        role.name, blocker, panel.get("id"), guild.id,
                    )

            if to_remove:
                await self._change_roles(member, to_remove, "remove")
            if addable:
                await self._change_roles(member, addable, "add")

            held = self.held_panel_roles(member, panel_role_ids)

        text = self._chooser_text(panel, entries, held)
        if blocked:
            text += "\n-# Nicht vergeben: " + ", ".join(blocked) + " – bitte melde dich beim Team."

        await interaction.edit_original_response(
            content=text,
            view=SelfRoleChooserView(self, panel, entries, held),
            allowed_mentions=NO_PING,
        )

    async def _change_roles(
        self, member: discord.Member, roles: List[discord.Role], action: str
    ) -> bool:
        reason = (
            "Self-Role über Panel gewählt" if action == "add" else "Self-Role über Panel abgewählt"
        )
        try:
            if action == "add":
                await member.add_roles(*roles, reason=reason)
            else:
                await member.remove_roles(*roles, reason=reason)
        except discord.Forbidden:
            logger.warning(
                "Self-Role: keine Berechtigung für %s der Rollen %s bei %s (Guild %s).",
                action,
                ", ".join(role.name for role in roles),
                member.id,
                member.guild.id,
            )
            return False
        except discord.HTTPException:
            logger.exception(
                "Self-Role: %s der Rollen %s bei %s fehlgeschlagen.",
                action,
                ", ".join(role.name for role in roles),
                member.id,
            )
            return False

        self._remember_role_state(
            member.guild.id, member.id, [role.id for role in roles], action == "add"
        )
        return True

    # ── Channel & Deploy ──

    async def _get_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        raw = await self.api.get_config(str(guild.id), SELFROLE_CHANNEL_CONFIG_KEY)
        if not raw:
            return None
        try:
            channel = guild.get_channel(int(raw))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _sorted_panels(self, guild_id: int) -> List[Dict[str, Any]]:
        panels = await self.api.get_all_selfrole_panels(str(guild_id))
        return sorted(
            (p for p in (panels or []) if isinstance(p, dict)),
            key=lambda p: int(p.get("id") or 0),
        )

    async def _sync_panel_mappings(
        self, guild: discord.Guild, panel: Dict[str, Any]
    ) -> List[PanelEntry]:
        """Verschwundene Rollen entfernen und offene Emojis nachziehen.

        Gesetzte Emojis bleiben unangetastet – nur Platzhalter und die
        Farbklekse aus der ersten Version werden neu bestimmt.
        """
        entries = resolve_entries(guild, panel)
        preset = {entry.role.id: entry.emoji for entry in entries}
        remapped = build_entries(guild, [entry.role for entry in entries], preset)

        after = [(entry.emoji, str(entry.role.id)) for entry in remapped]
        stored = [(str(e), str(r)) for e, r in (panel.get("roles") or {}).items()]

        if after != stored:
            await self.api.replace_selfrole_mappings(int(panel["id"]), after)
            panel["roles"] = {emoji: role_id for emoji, role_id in after}

        return remapped

    async def deploy_panels(
        self, guild: discord.Guild, *, repost: bool = False
    ) -> Tuple[int, int, List[str]]:
        """Erzeugt oder aktualisiert alle Panel-Nachrichten. (neu, aktualisiert, Fehler)"""
        lock = self._deploy_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            channel = await self._get_channel(guild)
            if channel is None:
                return 0, 0, ["Es ist kein Self-Role Channel gesetzt (`/selfroles channel`)."]

            created = 0
            updated = 0
            problems: List[str] = []

            for panel in await self._sorted_panels(guild.id):
                try:
                    entries = await self._sync_panel_mappings(guild, panel)
                    content = render_panel_message(panel, entries)
                    view = panel_view(panel)

                    message = None
                    if not repost:
                        message = await self._existing_message(guild, channel, panel)

                    if message is not None:
                        await message.edit(
                            content=content, view=view, allowed_mentions=NO_PING
                        )
                        updated += 1
                    else:
                        message = await channel.send(
                            content=content, view=view, allowed_mentions=NO_PING
                        )
                        await self.api.set_selfrole_panel_message(
                            int(panel["id"]), str(message.id), str(channel.id)
                        )
                        created += 1
                except discord.Forbidden:
                    problems.append(
                        f"**{panel.get('title')}**: mir fehlen Rechte in {channel.mention}."
                    )
                except discord.HTTPException:
                    logger.exception(
                        "Self-Role Deploy für Panel %s fehlgeschlagen.", panel.get("id")
                    )
                    problems.append(f"**{panel.get('title')}**: Discord-Fehler beim Senden.")

            return created, updated, problems

    async def _existing_message(
        self, guild: discord.Guild, channel: discord.TextChannel, panel: Dict[str, Any]
    ) -> Optional[discord.Message]:
        message_id = panel.get("message_id")
        stored_channel = str(panel.get("channel_id") or "")
        if not message_id or stored_channel != str(channel.id):
            return None
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            return None
        if self.bot.user is None or message.author.id != self.bot.user.id:
            return None
        return message

    # ── Commands ──

    selfroles_group = app_commands.Group(
        name="selfroles",
        description="Selfrole-Kategorien verwalten.",
    )

    async def _staff_guard(self, interaction: discord.Interaction) -> Optional[discord.Guild]:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.", ephemeral=True
            )
            return None
        if not is_selfrole_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return None
        return guild

    @selfroles_group.command(
        name="channel", description="Legt den Channel fest, in dem die Rollen-Nachrichten stehen."
    )
    @app_commands.describe(kanal="Textkanal für die Self-Role Nachrichten")
    async def selfroles_channel(
        self, interaction: discord.Interaction, kanal: discord.TextChannel
    ):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        await self.api.set_config(
            str(guild.id), SELFROLE_CHANNEL_CONFIG_KEY, str(kanal.id)
        )
        await interaction.response.send_message(
            f"Self-Role Channel ist jetzt {kanal.mention}.\n"
            "Mit `/selfroles deploy` erzeugst du dort die Nachrichten.",
            ephemeral=True,
        )

    @selfroles_group.command(
        name="create", description="Legt eine neue Rollen-Kategorie an."
    )
    @app_commands.describe(
        titel="Titel der Kategorie, gern mit Emoji davor (z. B. 🎮 Gaming)",
        limit="Max. Rollen aus dieser Kategorie (0 = unbegrenzt, 1 = Einzelauswahl)",
        rollen="Rollen hintereinander erwähnen. Optional je Rolle ein Emoji dahinter, sonst automatisch.",
    )
    async def selfroles_create(
        self,
        interaction: discord.Interaction,
        titel: str,
        limit: int,
        rollen: str,
    ):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        if limit < 0:
            await interaction.response.send_message(
                "Das Limit muss >= 0 sein.", ephemeral=True
            )
            return

        channel = await self._get_channel(guild)
        if channel is None:
            await interaction.response.send_message(
                "Setze zuerst den Self-Role Channel mit `/selfroles channel`.",
                ephemeral=True,
            )
            return

        wanted, problems = self._parse_roles(guild, rollen)
        if not wanted:
            hint = "\n" + "\n".join(problems) if problems else ""
            await interaction.response.send_message(
                f"Ich konnte keine nutzbaren Rollen erkennen.{hint}", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        entries = build_entries(
            guild,
            [role for role, _ in wanted],
            {role.id: emoji for role, emoji in wanted if emoji},
        )
        panel: Dict[str, Any] = {"id": 0, "title": titel, "max_roles": limit}

        message = await channel.send(
            content=render_panel_message(panel, entries),
            allowed_mentions=NO_PING,
        )

        stored = await self.api.create_selfrole_panel(
            str(guild.id),
            str(message.id),
            str(channel.id),
            titel,
            limit,
            {entry.emoji: str(entry.role.id) for entry in entries},
        )
        if not stored:
            await message.delete()
            await interaction.followup.send(
                "Die Kategorie konnte nicht gespeichert werden. Details stehen im Bot-Log.",
                ephemeral=True,
            )
            return

        await message.edit(
            content=render_panel_message(stored, entries),
            view=panel_view(stored),
            allowed_mentions=NO_PING,
        )

        note = "\n" + "\n".join(problems) if problems else ""
        await interaction.followup.send(
            f"Kategorie **{titel}** mit {len(entries)} Rolle(n) in {channel.mention} angelegt.{note}",
            ephemeral=True,
        )

    def _parse_roles(
        self, guild: discord.Guild, raw: str
    ) -> Tuple[List[Tuple[discord.Role, Optional[str]]], List[str]]:
        """Liest `@Rolle [Emoji] @Rolle [Emoji] …` – das Emoji ist überall optional."""
        wanted: List[Tuple[discord.Role, Optional[str]]] = []
        problems: List[str] = []
        seen: Set[int] = set()
        used_emojis: Set[str] = set()

        tokens = raw.split()
        index = 0
        while index < len(tokens):
            token = tokens[index].strip().strip(",")
            index += 1

            candidate = token[3:-1] if token.startswith("<@&") and token.endswith(">") else token
            if not candidate.isdigit():
                continue

            emoji: Optional[str] = None
            if index < len(tokens) and EMOJI_PREFIX_RE.fullmatch(tokens[index]):
                emoji = tokens[index].strip()
                index += 1

            role = guild.get_role(int(candidate))
            if role is None:
                problems.append(f"-# Rolle `{candidate}` existiert nicht.")
                continue
            if role.id in seen:
                continue

            blocker = role_blocker(guild, role)
            if blocker is not None:
                problems.append(f"-# {role.name}: {blocker}.")
                continue

            if len(wanted) >= MAX_ROLES_PER_PANEL:
                problems.append(
                    f"-# Nur {MAX_ROLES_PER_PANEL} Rollen pro Kategorie möglich, Rest ignoriert."
                )
                break

            if emoji and emoji in used_emojis:
                problems.append(f"-# {emoji} war doppelt, {role.name} bekommt ein anderes.")
                emoji = None
            if emoji:
                used_emojis.add(emoji)

            seen.add(role.id)
            wanted.append((role, emoji))

        return wanted, problems

    @selfroles_group.command(
        name="edit", description="Fügt einer Kategorie eine Rolle hinzu oder entfernt sie."
    )
    @app_commands.describe(
        kategorie="Titel der Kategorie",
        aktion="Rolle hinzufügen oder entfernen",
        rolle="Die Rolle",
    )
    @app_commands.choices(
        aktion=[
            app_commands.Choice(name="Rolle hinzufügen", value="add"),
            app_commands.Choice(name="Rolle entfernen", value="remove"),
        ]
    )
    async def selfroles_edit(
        self,
        interaction: discord.Interaction,
        kategorie: str,
        aktion: app_commands.Choice[str],
        rolle: discord.Role,
    ):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        panel = await self._find_panel(guild, kategorie)
        if panel is None:
            await interaction.response.send_message(
                await self._unknown_panel_text(guild, kategorie), ephemeral=True
            )
            return

        entries = resolve_entries(guild, panel)
        roles = [entry.role for entry in entries]

        if aktion.value == "add":
            if rolle.id in {role.id for role in roles}:
                await interaction.response.send_message(
                    f"{rolle.mention} ist in **{panel['title']}** bereits enthalten.",
                    ephemeral=True,
                )
                return
            if len(roles) >= MAX_ROLES_PER_PANEL:
                await interaction.response.send_message(
                    f"**{panel['title']}** hat bereits {MAX_ROLES_PER_PANEL} Rollen – mehr erlaubt Discord im Menü nicht.",
                    ephemeral=True,
                )
                return
            blocker = role_blocker(guild, rolle)
            if blocker is not None:
                await interaction.response.send_message(
                    f"{rolle.mention} kann nicht vergeben werden: {blocker}.", ephemeral=True
                )
                return
            roles.append(rolle)
        else:
            if rolle.id not in {role.id for role in roles}:
                await interaction.response.send_message(
                    f"{rolle.mention} ist in **{panel['title']}** nicht enthalten.",
                    ephemeral=True,
                )
                return
            roles = [role for role in roles if role.id != rolle.id]

        await interaction.response.defer(ephemeral=True, thinking=True)

        preset = {entry.role.id: entry.emoji for entry in entries}
        remapped = build_entries(guild, roles, preset)
        await self._store_entries(panel, remapped)
        await self._refresh_panel_message(guild, panel, remapped)

        verb = "hinzugefügt" if aktion.value == "add" else "entfernt"
        await interaction.followup.send(
            f"**{panel['title']}**: {rolle.mention} {verb}.", ephemeral=True
        )

    async def _store_entries(
        self, panel: Dict[str, Any], entries: List[PanelEntry]
    ) -> None:
        pairs = [(entry.emoji, str(entry.role.id)) for entry in entries]
        await self.api.replace_selfrole_mappings(int(panel["id"]), pairs)
        panel["roles"] = {emoji: role_id for emoji, role_id in pairs}

    @selfroles_group.command(
        name="emoji", description="Setzt das Emoji einer Rolle in einer Kategorie."
    )
    @app_commands.describe(
        kategorie="Titel der Kategorie",
        rolle="Die Rolle",
        emoji="Emoji, oder `-` für kein Emoji",
    )
    async def selfroles_emoji(
        self,
        interaction: discord.Interaction,
        kategorie: str,
        rolle: discord.Role,
        emoji: str,
    ):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        panel = await self._find_panel(guild, kategorie)
        if panel is None:
            await interaction.response.send_message(
                await self._unknown_panel_text(guild, kategorie), ephemeral=True
            )
            return

        entries = resolve_entries(guild, panel)
        if rolle.id not in {entry.role.id for entry in entries}:
            await interaction.response.send_message(
                f"{rolle.mention} ist in **{panel['title']}** nicht enthalten.",
                ephemeral=True,
            )
            return

        wanted = emoji.strip()
        clear = wanted in {"-", "–", "none", "kein"}

        if not clear:
            if not EMOJI_PREFIX_RE.fullmatch(wanted):
                await interaction.response.send_message(
                    f"`{wanted}` sieht nicht nach einem Emoji aus. "
                    "Nutze ein Standard-Emoji, ein Server-Emoji oder `-` für keins.",
                    ephemeral=True,
                )
                return
            if any(
                entry.emoji == wanted and entry.role.id != rolle.id for entry in entries
            ):
                await interaction.response.send_message(
                    f"{wanted} ist in **{panel['title']}** schon vergeben.", ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        preset = {entry.role.id: entry.emoji for entry in entries}
        preset[rolle.id] = wanted
        remapped = build_entries(guild, [entry.role for entry in entries], preset)

        if clear:
            # build_entries würde für einen Platzhalter wieder automatisch
            # nachbessern – hier ist "kein Emoji" aber ausdrücklich gewollt.
            for entry in remapped:
                if entry.role.id == rolle.id:
                    entry.emoji = placeholder_emoji(rolle.id)

        await self._store_entries(panel, remapped)
        await self._refresh_panel_message(guild, panel, remapped)

        target = next(e for e in remapped if e.role.id == rolle.id)
        await interaction.followup.send(
            f"**{panel['title']}**: {rolle.mention} → {role_chip(target)}", ephemeral=True
        )

    @selfroles_group.command(
        name="limit", description="Ändert das Auswahl-Limit einer Kategorie."
    )
    @app_commands.describe(
        kategorie="Titel der Kategorie",
        limit="0 = unbegrenzt, 1 = Einzelauswahl, sonst Maximum",
    )
    async def selfroles_limit(
        self, interaction: discord.Interaction, kategorie: str, limit: int
    ):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        if limit < 0:
            await interaction.response.send_message(
                "Das Limit muss >= 0 sein.", ephemeral=True
            )
            return

        panel = await self._find_panel(guild, kategorie)
        if panel is None:
            await interaction.response.send_message(
                await self._unknown_panel_text(guild, kategorie), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        await self.api.update_selfrole_panel(int(panel["id"]), max_roles=limit)
        panel["max_roles"] = limit
        await self._refresh_panel_message(guild, panel, resolve_entries(guild, panel))

        await interaction.followup.send(
            f"**{panel['title']}**: Limit auf "
            f"{'unbegrenzt' if limit == 0 else limit} gesetzt.",
            ephemeral=True,
        )

    @selfroles_group.command(name="delete", description="Löscht eine Rollen-Kategorie.")
    @app_commands.describe(kategorie="Titel der Kategorie")
    async def selfroles_delete(self, interaction: discord.Interaction, kategorie: str):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        panel = await self._find_panel(guild, kategorie)
        if panel is None:
            await interaction.response.send_message(
                await self._unknown_panel_text(guild, kategorie), ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = await self._get_channel(guild)
        if channel is not None:
            message = await self._existing_message(guild, channel, panel)
            if message is not None:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass

        await self.api.delete_selfrole_panel_by_id(int(panel["id"]))
        await interaction.followup.send(
            f"Kategorie **{panel['title']}** wurde gelöscht.", ephemeral=True
        )

    @selfroles_group.command(
        name="deploy",
        description="Erzeugt bzw. aktualisiert alle Rollen-Nachrichten im Self-Role Channel.",
    )
    @app_commands.describe(
        neu_senden="Alte Nachrichten ignorieren und alles neu posten (z. B. nach Channel-Wechsel)."
    )
    async def selfroles_deploy(
        self, interaction: discord.Interaction, neu_senden: bool = False
    ):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        created, updated, problems = await self.deploy_panels(guild, repost=neu_senden)

        parts = []
        if created:
            parts.append(f"{created} neu gepostet")
        if updated:
            parts.append(f"{updated} aktualisiert")
        summary = ", ".join(parts) if parts else "Keine Kategorien vorhanden"

        note = "\n" + "\n".join(problems) if problems else ""
        await interaction.followup.send(f"Deploy fertig: {summary}.{note}", ephemeral=True)

    @selfroles_group.command(name="list", description="Zeigt alle Rollen-Kategorien.")
    async def selfroles_list(self, interaction: discord.Interaction):
        guild = await self._staff_guard(interaction)
        if guild is None:
            return

        panels = await self._sorted_panels(guild.id)
        if not panels:
            await interaction.response.send_message(
                "Es sind noch keine Rollen-Kategorien angelegt.", ephemeral=True
            )
            return

        channel = await self._get_channel(guild)
        lines = [
            f"Self-Role Channel: {channel.mention if channel else '**nicht gesetzt**'}",
            "",
        ]
        for panel in panels:
            entries = resolve_entries(guild, panel)
            max_roles = panel_max_roles(panel)
            mode = "Einzelauswahl" if max_roles == 1 else (
                "unbegrenzt" if max_roles == 0 else f"max. {max_roles}"
            )
            lines.append(f"**{panel.get('title')}** · {mode} · {len(entries)} Rolle(n)")
            lines.append(
                "-# " + (" · ".join(role_chip(entry) for entry in entries) or "keine Rollen")
            )

        await interaction.response.send_message(
            "\n".join(lines)[:2000], ephemeral=True, allowed_mentions=NO_PING
        )

    async def _find_panel(
        self, guild: discord.Guild, title: str
    ) -> Optional[Dict[str, Any]]:
        wanted = title.strip().lower()
        for panel in await self._sorted_panels(guild.id):
            stored = str(panel.get("title") or "")
            if stored.lower() == wanted or split_emoji(stored)[1].lower() == wanted:
                return panel
        return None

    async def _unknown_panel_text(self, guild: discord.Guild, title: str) -> str:
        panels = await self._sorted_panels(guild.id)
        available = ", ".join(f"**{p.get('title')}**" for p in panels)
        return (
            f"Keine Kategorie mit dem Titel **{title}** gefunden.\n"
            f"Vorhanden: {available or 'keine'}"
        )

    async def _refresh_panel_message(
        self,
        guild: discord.Guild,
        panel: Dict[str, Any],
        entries: List[PanelEntry],
    ) -> None:
        channel = await self._get_channel(guild)
        if channel is None:
            return
        message = await self._existing_message(guild, channel, panel)
        if message is None:
            return
        try:
            await message.edit(
                content=render_panel_message(panel, entries),
                view=panel_view(panel),
                allowed_mentions=NO_PING,
            )
        except discord.HTTPException:
            logger.exception(
                "Self-Role: Nachricht für Panel %s konnte nicht aktualisiert werden.",
                panel.get("id"),
            )

    # ── Selbstheilung ──

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # on_ready feuert bei jedem Reconnect – ohne Guard würden die Panels
        # bei jedem Netzwerkhänger neu durch die API geschickt.
        for guild in self.bot.guilds:
            if guild.id in self._startup_synced:
                continue
            try:
                created, updated, problems = await self.deploy_panels(guild)
                if created or updated:
                    logger.info(
                        "Self-Role: Guild %s – %s neu, %s aktualisiert.",
                        guild.id, created, updated,
                    )
                for problem in problems:
                    logger.warning("Self-Role: Guild %s – %s", guild.id, problem)
                if not problems:
                    self._startup_synced.add(guild.id)
            except Exception:
                logger.exception("Self-Role Startsync für Guild %s fehlgeschlagen", guild.id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if before.name == after.name and before.unicode_emoji == after.unicode_emoji:
            return
        await self._refresh_panels_with_role(after.guild, after.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self._refresh_panels_with_role(role.guild, role.id)

    async def _refresh_panels_with_role(self, guild: discord.Guild, role_id: int) -> None:
        try:
            for panel in await self._sorted_panels(guild.id):
                stored_ids = {str(rid) for rid in (panel.get("roles") or {}).values()}
                if str(role_id) not in stored_ids:
                    continue
                entries = await self._sync_panel_mappings(guild, panel)
                await self._refresh_panel_message(guild, panel, entries)
        except Exception:
            logger.exception(
                "Self-Role: Auto-Refresh nach Rollenänderung (%s) fehlgeschlagen", role_id
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(SelfRolesCog(bot))
