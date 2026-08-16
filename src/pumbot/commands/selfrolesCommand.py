from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger

SELFROLE_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}

# Pause nach jedem Rollen-Request, damit Discord nicht rate-limitet.
ROLE_ACTION_DELAY_SECONDS = 0.8
# So lange gilt eine gerade angewandte Rollenänderung als Wahrheit, auch wenn
# der Member-Cache das GUILD_MEMBER_UPDATE noch nicht gesehen hat.
ROLE_STATE_TTL_SECONDS = 30.0
# So lange merken wir uns Reaktionen, die der Bot selbst entfernt hat.
IGNORED_REMOVAL_TTL_SECONDS = 60.0
# So lange gilt die Liste der Panel-Nachrichten einer Guild als aktuell.
PANEL_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class ReactionIntent:
    guild_id: int
    member_id: int
    channel_id: int
    message_id: int
    emoji: str
    action: str


def is_selfrole_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name in SELFROLE_STAFF_ROLES for r in member.roles)


def panel_role_map(panel: Dict[str, Any]) -> Dict[str, int]:
    """Emoji -> Rollen-ID, ungültige Einträge werden verworfen."""
    result: Dict[str, int] = {}
    for emoji, role_id in (panel.get("roles") or {}).items():
        try:
            result[str(emoji)] = int(role_id)
        except (TypeError, ValueError):
            continue
    return result


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


class SelfRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self._reaction_queue: asyncio.Queue[ReactionIntent] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        # (guild_id, member_id) -> {role_id: (hat_rolle, timestamp)}
        self._pending_roles: Dict[Tuple[int, int], Dict[int, Tuple[bool, float]]] = {}
        # (message_id, member_id, emoji) -> timestamp
        self._ignored_removals: Dict[Tuple[int, int, str], float] = {}
        # guild_id -> (Panel-Message-IDs, timestamp)
        self._panel_messages: Dict[int, Tuple[Set[int], float]] = {}

    async def cog_load(self) -> None:
        self._worker_task = asyncio.create_task(self._reaction_worker())

    async def cog_unload(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("cog_unload error (SelfRolesCog)")

    # ── Zustandsverwaltung ──

    def _remember_role_state(
        self, guild_id: int, member_id: int, role_ids: List[int], has_role: bool
    ) -> None:
        state = self._pending_roles.setdefault((guild_id, member_id), {})
        now = time.monotonic()
        for role_id in role_ids:
            state[role_id] = (has_role, now)

    def _effective_panel_roles(
        self, member: discord.Member, panel_role_ids: Set[int]
    ) -> Set[int]:
        """Rollen aus diesem Panel, die der Member hat.

        Der Member-Cache hinkt hinter unseren eigenen Änderungen her, weil
        Discord die Rollen erst per Gateway-Event zurückmeldet. Ohne dieses
        Overlay sieht ein zweiter Klick in derselben Sekunde den alten Stand
        und das Panel-Limit greift nicht.
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

    async def _is_panel_message(self, guild_id: int, message_id: int) -> bool:
        """Filtert Reaktionen auf normale Nachrichten raus, bevor sie die Queue erreichen."""
        cached = self._panel_messages.get(guild_id)
        now = time.monotonic()
        if cached is None or now - cached[1] > PANEL_CACHE_TTL_SECONDS:
            panels = await self.api.get_all_selfrole_panels(str(guild_id))
            message_ids: Set[int] = set()
            for panel in panels or []:
                if not isinstance(panel, dict):
                    continue
                try:
                    message_ids.add(int(panel.get("message_id")))
                except (TypeError, ValueError):
                    continue
            cached = (message_ids, now)
            self._panel_messages[guild_id] = cached
        return message_id in cached[0]

    def _invalidate_panel_cache(self, guild_id: int) -> None:
        self._panel_messages.pop(guild_id, None)

    def _mark_ignored_removal(self, message_id: int, member_id: int, emoji: str) -> None:
        now = time.monotonic()
        for key, created_at in list(self._ignored_removals.items()):
            if now - created_at > IGNORED_REMOVAL_TTL_SECONDS:
                self._ignored_removals.pop(key, None)
        self._ignored_removals[(message_id, member_id, emoji)] = now

    def _consume_ignored_removal(
        self, message_id: int, member_id: int, emoji: str
    ) -> bool:
        key = (message_id, member_id, emoji)
        created_at = self._ignored_removals.pop(key, None)
        if created_at is None:
            return False
        return time.monotonic() - created_at <= IGNORED_REMOVAL_TTL_SECONDS

    # ── Discord-Aktionen ──

    async def _fetch_panel_message(
        self, guild: discord.Guild, channel_id: int, message_id: int
    ) -> discord.Message | None:
        channel = guild.get_channel_or_thread(channel_id) or guild.get_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            return None
        try:
            return await channel.fetch_message(message_id)
        except discord.HTTPException:
            return None

    async def _remove_member_reaction(
        self, message: discord.Message, member: discord.Member, emoji: str
    ) -> None:
        self._mark_ignored_removal(message.id, member.id, emoji)
        try:
            await message.remove_reaction(emoji, member)
        except discord.HTTPException:
            self._ignored_removals.pop((message.id, member.id, emoji), None)

    async def _apply_role_change(
        self, member: discord.Member, roles: List[discord.Role], action: str
    ) -> bool:
        if not roles:
            return False

        reason = (
            "Self-Role per Reaktion hinzugefügt"
            if action == "add"
            else "Self-Role per Reaktion entfernt"
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
        await asyncio.sleep(ROLE_ACTION_DELAY_SECONDS)
        return True

    # ── Worker ──

    async def _reaction_worker(self) -> None:
        while True:
            try:
                intent = await self._reaction_queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._handle_intent(intent)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Self-Role Worker: Intent %r fehlgeschlagen", intent)
            finally:
                self._reaction_queue.task_done()

    async def _handle_intent(self, intent: ReactionIntent) -> None:
        guild = self.bot.get_guild(intent.guild_id)
        if guild is None:
            return

        member = guild.get_member(intent.member_id)
        if member is None or member.bot:
            return

        panel = await self.api.get_selfrole_panel(
            str(intent.guild_id), str(intent.message_id)
        )
        if not panel:
            return

        roles_map = panel_role_map(panel)
        role_id = roles_map.get(intent.emoji)
        if role_id is None:
            return

        role = guild.get_role(role_id)
        if role is None:
            logger.warning(
                "Self-Role: Rolle %s aus Panel %s existiert nicht mehr.",
                role_id,
                intent.message_id,
            )
            return

        panel_role_ids = set(roles_map.values())
        held = self._effective_panel_roles(member, panel_role_ids)

        if intent.action == "remove":
            if role.id not in held:
                return
            await self._apply_role_change(member, [role], "remove")
            return

        if role.id in held:
            return

        blocker = role_blocker(guild, role)
        if blocker is not None:
            logger.warning(
                "Self-Role: %s kann nicht vergeben werden (%s). Panel %s, Guild %s.",
                role.name,
                blocker,
                intent.message_id,
                guild.id,
            )
            await self._reject_reaction(
                intent,
                guild,
                member,
                f"{member.mention}, die Rolle **{role.name}** kann ich gerade nicht vergeben "
                f"({blocker}). Bitte melde dich beim Team.",
            )
            return

        try:
            max_roles = int(panel.get("max_roles") or 0)
        except (TypeError, ValueError):
            max_roles = 0

        if max_roles > 0 and len(held) >= max_roles:
            if max_roles == 1:
                released = await self._release_previous_roles(
                    intent, guild, member, roles_map, held
                )
                if not released:
                    # Alte Rolle blieb hängen – die neue jetzt zu vergeben würde
                    # das Limit erst recht brechen.
                    await self._reject_reaction(
                        intent,
                        guild,
                        member,
                        f"{member.mention}, ich konnte deine bisherige Rolle aus diesem "
                        "Panel nicht entfernen. Bitte melde dich beim Team.",
                    )
                    return
            else:
                await self._reject_reaction(
                    intent,
                    guild,
                    member,
                    f"{member.mention}, du hast bereits die maximale Anzahl an Rollen "
                    f"({max_roles}) aus dieser Self-Role Nachricht.",
                )
                return

        await self._apply_role_change(member, [role], "add")

    async def _release_previous_roles(
        self,
        intent: ReactionIntent,
        guild: discord.Guild,
        member: discord.Member,
        roles_map: Dict[str, int],
        held: Set[int],
    ) -> bool:
        """Panel mit Limit 1: alte Rolle abgeben, bevor die neue kommt."""
        stale_roles = [role for role in (guild.get_role(rid) for rid in held) if role]
        if not stale_roles:
            return True

        if not await self._apply_role_change(member, stale_roles, "remove"):
            return False

        message = await self._fetch_panel_message(
            guild, intent.channel_id, intent.message_id
        )
        if message is None:
            return True

        stale_ids = {role.id for role in stale_roles}
        for emoji, role_id in roles_map.items():
            if role_id in stale_ids and emoji != intent.emoji:
                await self._remove_member_reaction(message, member, emoji)
        return True

    async def _reject_reaction(
        self,
        intent: ReactionIntent,
        guild: discord.Guild,
        member: discord.Member,
        notice: str,
    ) -> None:
        message = await self._fetch_panel_message(
            guild, intent.channel_id, intent.message_id
        )
        if message is None:
            return

        await self._remove_member_reaction(message, member, intent.emoji)
        try:
            await message.channel.send(notice, delete_after=15)
        except discord.HTTPException:
            pass

    # ── Commands ──

    selfroles_group = app_commands.Group(
        name="selfroles",
        description="Selfrole-Verwaltung (Panel erstellen/bearbeiten).",
    )

    @selfroles_group.command(name="create", description="Erstellt ein Self-Role Panel.")
    @app_commands.describe(
        titel="Titel des Panels",
        limit="Max. Anzahl Rollen aus diesem Panel (0 = unbegrenzt)",
        rollen_und_emojis="Paare im Format: @Rolle Emoji @Rolle Emoji ...",
    )
    async def selfroles_create(
        self,
        interaction: discord.Interaction,
        titel: str,
        limit: int,
        rollen_und_emojis: str,
    ):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_selfrole_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        if limit < 0:
            await interaction.response.send_message(
                "Das Limit muss >= 0 sein.", ephemeral=True
            )
            return

        pairs, blocked = self._parse_role_emoji_pairs(guild, rollen_und_emojis)

        if not pairs:
            hint = "\n" + "\n".join(blocked) if blocked else ""
            await interaction.response.send_message(
                f"Ich konnte keine nutzbaren Rollen/Emoji-Paare erkennen.{hint}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title=titel,
                description="Panel wird eingerichtet …",
                color=discord.Color.blurple(),
            )
        )
        message = await interaction.original_response()

        roles_map: Dict[str, int] = {}
        lines: List[str] = []
        for emoji, role in pairs:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                blocked.append(f"`{emoji}` ist kein Emoji, das ich setzen kann.")
                continue
            roles_map[emoji] = role.id
            lines.append(f"{emoji} {role.mention}")

        if not roles_map:
            await message.edit(
                embed=discord.Embed(
                    title=titel,
                    description="Keine der angegebenen Emojis konnte gesetzt werden.",
                    color=discord.Color.red(),
                )
            )
            await interaction.followup.send(
                "Panel wurde nicht gespeichert.\n" + "\n".join(blocked),
                ephemeral=True,
            )
            return

        await message.edit(
            embed=discord.Embed(
                title=f"{titel} (Limit: {limit if limit > 0 else 'unbegrenzt'})",
                description=(
                    "Reagiere, um Rollen zu erhalten oder zu entfernen.\n\n"
                    + "\n".join(lines)
                ),
                color=discord.Color.blurple(),
            )
        )

        await self.api.create_selfrole_panel(
            str(guild.id),
            str(message.id),
            str(message.channel.id),
            titel,
            limit,
            roles_map,
        )
        self._invalidate_panel_cache(guild.id)

        if blocked:
            await interaction.followup.send(
                "Panel gespeichert, aber diese Angaben wurden übersprungen:\n"
                + "\n".join(blocked),
                ephemeral=True,
            )

    def _parse_role_emoji_pairs(
        self, guild: discord.Guild, raw: str
    ) -> Tuple[List[Tuple[str, discord.Role]], List[str]]:
        tokens = raw.split()
        pairs: List[Tuple[str, discord.Role]] = []
        blocked: List[str] = []
        used_emojis: Set[str] = set()
        used_roles: Set[int] = set()

        i = 0
        while i < len(tokens):
            token = tokens[i]
            if not (token.startswith("<@&") and token.endswith(">")):
                i += 1
                continue

            try:
                role_id = int(token[3:-1])
            except ValueError:
                i += 1
                continue

            role = guild.get_role(role_id)
            if role is None:
                blocked.append(f"Rolle `{role_id}` existiert nicht mehr.")
                i += 1
                continue

            if i + 1 >= len(tokens):
                blocked.append(f"Für {role.name} fehlt das Emoji.")
                break

            emoji = tokens[i + 1]
            i += 2

            if emoji in used_emojis:
                blocked.append(f"`{emoji}` wurde mehrfach angegeben.")
                continue
            if role.id in used_roles:
                blocked.append(f"{role.name} wurde mehrfach angegeben.")
                continue

            blocker = role_blocker(guild, role)
            if blocker is not None:
                blocked.append(f"{role.name}: {blocker}.")
                continue

            used_emojis.add(emoji)
            used_roles.add(role.id)
            pairs.append((emoji, role))

        return pairs, blocked

    @selfroles_group.command(
        name="edit", description="Bearbeitet ein bestehendes Self-Role Panel."
    )
    @app_commands.describe(
        panel_titel="Titel des Panels",
        aktion="add oder remove",
        rolle="Rolle",
        emoji="Emoji",
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
        panel_titel: str,
        aktion: app_commands.Choice[str],
        rolle: discord.Role,
        emoji: str,
    ):
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        if not is_selfrole_staff(interaction.user):
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        panels = await self.api.get_all_selfrole_panels(str(guild.id))
        if not panels:
            await interaction.response.send_message(
                "Für diesen Server existieren noch keine Self-Role Panels.",
                ephemeral=True,
            )
            return

        panel_title_lower = panel_titel.strip().lower()
        target_panel: Dict[str, Any] | None = None
        for panel in panels:
            if not isinstance(panel, dict):
                continue
            if str(panel.get("title", "")).lower() == panel_title_lower:
                target_panel = panel
                break

        if target_panel is None:
            available = ", ".join(
                f"**{p.get('title')}**" for p in panels if isinstance(p, dict)
            )
            await interaction.response.send_message(
                f"Kein Self-Role Panel mit dem Titel **{panel_titel}** gefunden.\n"
                f"Vorhanden: {available or 'keine'}",
                ephemeral=True,
            )
            return

        target_msg_id = target_panel.get("message_id")
        channel_id = target_panel.get("channel_id")
        if not target_msg_id or not channel_id:
            await interaction.response.send_message(
                "Für dieses Self-Role Panel ist kein Channel gespeichert.",
                ephemeral=True,
            )
            return

        message = await self._fetch_panel_message(
            guild, int(channel_id), int(target_msg_id)
        )
        if message is None:
            await interaction.response.send_message(
                "Die Panel-Nachricht konnte nicht geladen werden.", ephemeral=True
            )
            return

        roles_map = panel_role_map(target_panel)

        if aktion.value == "add":
            if emoji in roles_map:
                await interaction.response.send_message(
                    "Für dieses Emoji ist bereits eine Rolle in diesem Panel eingetragen.",
                    ephemeral=True,
                )
                return

            if rolle.id in roles_map.values():
                await interaction.response.send_message(
                    f"{rolle.mention} ist in diesem Panel bereits einem anderen Emoji zugeordnet.",
                    ephemeral=True,
                )
                return

            blocker = role_blocker(guild, rolle)
            if blocker is not None:
                await interaction.response.send_message(
                    f"{rolle.mention} kann nicht vergeben werden: {blocker}.",
                    ephemeral=True,
                )
                return

            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                await interaction.response.send_message(
                    f"`{emoji}` konnte nicht als Reaktion gesetzt werden. "
                    "Nutzt der Bot dieses Emoji nicht, funktioniert das Panel damit nicht.",
                    ephemeral=True,
                )
                return

            await self.api.add_selfrole_mapping(
                str(guild.id), str(target_msg_id), emoji, str(rolle.id)
            )
            self._invalidate_panel_cache(guild.id)
            roles_map[emoji] = rolle.id
            await self._refresh_panel_embed(message, target_panel, roles_map, guild)

            await interaction.response.send_message(
                f"Panel **{panel_titel}** aktualisiert: {rolle.mention} mit {emoji} hinzugefügt.",
                ephemeral=True,
            )
            return

        existing_role_id = roles_map.get(emoji)
        if existing_role_id is None:
            await interaction.response.send_message(
                "Für dieses Emoji ist keine Rolle in diesem Panel eingetragen.",
                ephemeral=True,
            )
            return

        if existing_role_id != rolle.id:
            await interaction.response.send_message(
                "Die Kombination aus Rolle und Emoji passt nicht zu diesem Panel.",
                ephemeral=True,
            )
            return

        await self.api.remove_selfrole_mapping(str(guild.id), str(target_msg_id), emoji)
        self._invalidate_panel_cache(guild.id)
        roles_map.pop(emoji, None)

        try:
            await message.clear_reaction(emoji)
        except discord.HTTPException:
            pass

        await self._refresh_panel_embed(message, target_panel, roles_map, guild)

        await interaction.response.send_message(
            f"Panel **{panel_titel}** aktualisiert: {rolle.mention} mit {emoji} entfernt.",
            ephemeral=True,
        )

    async def _refresh_panel_embed(
        self,
        message: discord.Message,
        panel: Dict[str, Any],
        roles_map: Dict[str, int],
        guild: discord.Guild,
    ) -> None:
        try:
            max_roles = int(panel.get("max_roles") or 0)
        except (TypeError, ValueError):
            max_roles = 0

        lines = []
        for emoji, role_id in roles_map.items():
            role = guild.get_role(role_id)
            lines.append(f"{emoji} {role.mention if role else f'`{role_id}`'}")

        embed = discord.Embed(
            title=f"{panel.get('title', 'Self-Roles')} "
            f"(Limit: {max_roles if max_roles > 0 else 'unbegrenzt'})",
            description=(
                "Reagiere, um Rollen zu erhalten oder zu entfernen.\n\n" + "\n".join(lines)
                if lines
                else "Aktuell sind keine Rollen hinterlegt."
            ),
            color=discord.Color.blurple(),
        )
        try:
            await message.edit(embed=embed)
        except discord.HTTPException:
            logger.exception("Self-Role: Panel-Embed %s konnte nicht aktualisiert werden.", message.id)

    # ── Events ──

    def _should_handle(self, payload: discord.RawReactionActionEvent) -> bool:
        if payload.guild_id is None:
            return False
        if self.bot.user and payload.user_id == self.bot.user.id:
            return False
        return True

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        try:
            if not self._should_handle(payload):
                return
            if not await self._is_panel_message(payload.guild_id, payload.message_id):
                return
            self._reaction_queue.put_nowait(
                ReactionIntent(
                    guild_id=payload.guild_id,
                    member_id=payload.user_id,
                    channel_id=payload.channel_id,
                    message_id=payload.message_id,
                    emoji=str(payload.emoji),
                    action="add",
                )
            )
        except Exception:
            logger.exception("on_raw_reaction_add error")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        try:
            if not self._should_handle(payload):
                return
            emoji = str(payload.emoji)
            if self._consume_ignored_removal(
                payload.message_id, payload.user_id, emoji
            ):
                return
            if not await self._is_panel_message(payload.guild_id, payload.message_id):
                return
            self._reaction_queue.put_nowait(
                ReactionIntent(
                    guild_id=payload.guild_id,
                    member_id=payload.user_id,
                    channel_id=payload.channel_id,
                    message_id=payload.message_id,
                    emoji=emoji,
                    action="remove",
                )
            )
        except Exception:
            logger.exception("on_raw_reaction_remove error")


async def setup(bot: commands.Bot):
    await bot.add_cog(SelfRolesCog(bot))
