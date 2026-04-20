from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger

SELFROLE_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}


def is_selfrole_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name in SELFROLE_STAFF_ROLES for r in member.roles)


class SelfRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api = bot.api
        self._role_queue: asyncio.Queue[
            Tuple[int, int, str, List[int], Optional[int]]
        ] = asyncio.Queue()
        self._role_worker_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._role_worker_task = asyncio.create_task(self._role_worker())

    async def cog_unload(self) -> None:
        if self._role_worker_task:
            self._role_worker_task.cancel()
            try:
                await self._role_worker_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("cog_unload error (SelfRolesCog)")

    async def _enqueue_role_change(
        self,
        guild_id: int,
        member_id: int,
        action: str,
        role_ids: List[int],
        channel_id: Optional[int] = None,
    ) -> None:
        try:
            await self._role_queue.put(
                (guild_id, member_id, action, role_ids, channel_id)
            )
        except Exception:
            logger.exception("_enqueue_role_change error")

    async def _fetch_payload_message(
        self, guild: discord.Guild, channel_id: int, message_id: int
    ) -> discord.Message | None:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return None
        try:
            return await channel.fetch_message(message_id)
        except discord.HTTPException:
            return None

    async def _remove_member_reactions_for_roles(
        self,
        guild: discord.Guild,
        member: discord.Member,
        panel: Dict[str, Any],
        role_ids: List[int],
        channel_id: int,
        message_id: int,
    ) -> None:
        if not role_ids:
            return

        message = await self._fetch_payload_message(guild, channel_id, message_id)
        if message is None:
            return

        roles_map: Dict[str, int] = panel.get("roles", {})
        role_id_set = set(role_ids)
        for emoji_str, mapped_role_id in roles_map.items():
            try:
                current_role_id = int(mapped_role_id)
            except (TypeError, ValueError):
                continue

            if current_role_id not in role_id_set:
                continue

            try:
                await message.remove_reaction(emoji_str, member)
            except discord.HTTPException:
                continue

    async def _role_worker(self):
        try:
            while True:
                guild_id, member_id, action, role_ids, channel_id = (
                    await self._role_queue.get()
                )
                try:
                    guild = self.bot.get_guild(guild_id)
                    if guild is None:
                        continue

                    member = guild.get_member(member_id)
                    if member is None:
                        continue

                    roles: List[discord.Role] = []
                    for rid in role_ids:
                        r = guild.get_role(rid)
                        if r:
                            roles.append(r)

                    if not roles:
                        continue

                    if action == "add":
                        try:
                            await member.add_roles(
                                *roles, reason="Self-Role per Reaktion hinzugefügt"
                            )
                        except discord.Forbidden:
                            pass
                        except discord.HTTPException as e:
                            logger.exception("Role worker add HTTPException: %r", e)
                        except Exception:
                            logger.exception("Role worker add unexpected error")

                    elif action == "remove":
                        try:
                            await member.remove_roles(
                                *roles, reason="Self-Role per Reaktion entfernt"
                            )
                        except discord.Forbidden:
                            pass
                        except discord.HTTPException as e:
                            logger.exception("Role worker remove HTTPException: %r", e)
                        except Exception:
                            logger.exception("Role worker remove unexpected error")

                    await asyncio.sleep(0.8)

                finally:
                    self._role_queue.task_done()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("_role_worker outer error")

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
        if interaction.guild is None:
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

        guild = interaction.guild

        tokens = rollen_und_emojis.split()
        roles_map: Dict[str, int] = {}
        lines: list[str] = []

        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.startswith("<@&") and tok.endswith(">"):
                try:
                    role_id = int(tok[3:-1])
                except ValueError:
                    i += 1
                    continue

                role = guild.get_role(role_id)
                if role is None:
                    i += 1
                    continue

                if i + 1 >= len(tokens):
                    break

                emoji = tokens[i + 1]
                emoji_key = emoji

                if emoji_key in roles_map:
                    i += 2
                    continue

                roles_map[emoji_key] = role.id
                lines.append(f"{emoji} {role.mention}")
                i += 2
            else:
                i += 1

        if not roles_map:
            await interaction.response.send_message(
                "Ich konnte keine gültigen Rollen/Emoji-Paare erkennen.",
                ephemeral=True,
            )
            return

        description = (
            "Reagiere, um Rollen zu erhalten oder zu entfernen.\n\n" + "\n".join(lines)
        )

        embed = discord.Embed(
            title=f"{titel} (Limit: {limit if limit > 0 else 'unbegrenzt'})",
            description=description,
            color=discord.Color.blurple(),
        )

        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()

        for emoji in roles_map.keys():
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                continue

        await self.api.create_selfrole_panel(
            str(guild.id),
            str(message.id),
            str(message.channel.id),
            titel,
            limit,
            roles_map,
        )

    @selfroles_group.command(
        name="edit", description="Bearbeitet ein bestehendes Self-Role Panel."
    )
    @app_commands.describe(
        panel_titel="Titel des Panels",
        aktion="add oder remove",
        rolle="Rolle",
        emoji="Emoji",
    )
    async def selfroles_edit(
        self,
        interaction: discord.Interaction,
        panel_titel: str,
        aktion: str,
        rolle: discord.Role,
        emoji: str,
    ):
        if interaction.guild is None:
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

        panels = await self.api.get_all_selfrole_panels(str(interaction.guild.id))
        if not panels:
            await interaction.response.send_message(
                "Für diesen Server existieren noch keine Self-Role Panels.",
                ephemeral=True,
            )
            return

        panel_title_lower = panel_titel.lower()
        target_panel: Dict[str, Any] | None = None

        for panel in panels:
            if not isinstance(panel, dict):
                continue
            if panel.get("title", "").lower() == panel_title_lower:
                target_panel = panel
                break

        if target_panel is None:
            await interaction.response.send_message(
                f"Kein Self-Role Panel mit dem Titel **{panel_titel}** gefunden.",
                ephemeral=True,
            )
            return

        target_msg_id = target_panel.get("message_id")
        channel_id = target_panel.get("channel_id")
        if target_msg_id is None or channel_id is None:
            await interaction.response.send_message(
                "Für dieses Self-Role Panel ist kein Channel gespeichert.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Der Kanal für dieses Self-Role Panel konnte nicht gefunden werden.",
                ephemeral=True,
            )
            return

        try:
            message = await channel.fetch_message(int(target_msg_id))
        except discord.NotFound:
            await interaction.response.send_message(
                "Die Panel-Nachricht wurde nicht gefunden.", ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                "Beim Abrufen der Panel-Nachricht ist ein Fehler aufgetreten.",
                ephemeral=True,
            )
            return

        roles_map: Dict[str, int] = target_panel.get("roles", {})
        aktion = aktion.lower()
        emoji_key = emoji

        if aktion == "add":
            if emoji_key in roles_map:
                await interaction.response.send_message(
                    "Für dieses Emoji ist bereits eine Rolle in diesem Panel eingetragen.",
                    ephemeral=True,
                )
                return

            await self.api.add_selfrole_mapping(
                str(interaction.guild.id), str(target_msg_id), emoji_key, rolle.id
            )

            try:
                await message.add_reaction(emoji_key)
            except discord.HTTPException:
                await interaction.response.send_message(
                    "Rolle gespeichert, Emoji konnte nicht hinzugefügt werden.",
                    ephemeral=True,
                )
                return

            await interaction.response.send_message(
                f"Panel **{panel_titel}** aktualisiert: {rolle.mention} mit {emoji_key} hinzugefügt.",
                ephemeral=True,
            )

        elif aktion == "remove":
            existing_role_id = roles_map.get(emoji_key)
            if not existing_role_id:
                await interaction.response.send_message(
                    "Für dieses Emoji ist keine Rolle in diesem Panel eingetragen.",
                    ephemeral=True,
                )
                return

            if int(existing_role_id) != rolle.id:
                await interaction.response.send_message(
                    "Die Kombination aus Rolle und Emoji passt nicht zu diesem Panel.",
                    ephemeral=True,
                )
                return

            await self.api.remove_selfrole_mapping(
                str(interaction.guild.id), str(target_msg_id), emoji_key
            )

            try:
                await message.clear_reaction(emoji_key)
            except discord.HTTPException:
                pass

            await interaction.response.send_message(
                f"Panel **{panel_titel}** aktualisiert: {rolle.mention} mit {emoji_key} entfernt.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Unbekannte Aktion. Nutze `add` oder `remove`.", ephemeral=True
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        try:
            if self.bot.user and payload.user_id == self.bot.user.id:
                return

            if payload.guild_id is None:
                return

            panel = await self.api.get_selfrole_panel(
                str(payload.guild_id), str(payload.message_id)
            )
            if not panel:
                return

            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return

            member = guild.get_member(payload.user_id)
            if member is None:
                return

            emoji_str = str(payload.emoji)
            roles_map: Dict[str, int] = panel.get("roles", {})
            role_id = roles_map.get(emoji_str)
            if not role_id:
                return

            role = guild.get_role(int(role_id))
            if role is None:
                return

            max_roles = int(panel.get("max_roles", 0) or 0)
            if max_roles > 0:
                current_roles = []
                for _, r_id in roles_map.items():
                    r = guild.get_role(int(r_id))
                    if r and r in member.roles:
                        current_roles.append(r)

                if len(current_roles) >= max_roles:
                    if max_roles == 1:
                        current_role_ids = [r.id for r in current_roles]
                        await self._enqueue_role_change(
                            guild.id,
                            member.id,
                            "remove",
                            current_role_ids,
                            payload.channel_id,
                        )
                        await self._remove_member_reactions_for_roles(
                            guild,
                            member,
                            panel,
                            current_role_ids,
                            payload.channel_id,
                            payload.message_id,
                        )
                    else:
                        channel = guild.get_channel(payload.channel_id)
                        if isinstance(channel, discord.TextChannel):
                            try:
                                message = await channel.fetch_message(
                                    payload.message_id
                                )
                                await message.remove_reaction(payload.emoji, member)
                            except discord.HTTPException:
                                pass

                            await channel.send(
                                f"{member.mention}, du hast bereits die maximale Anzahl an Rollen ({max_roles}) aus dieser Self-Role Nachricht.",
                                delete_after=10,
                            )
                        return

            await self._enqueue_role_change(
                guild.id,
                member.id,
                "add",
                [role.id],
                payload.channel_id,
            )

        except Exception:
            logger.exception("on_raw_reaction_add error")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        try:
            if payload.guild_id is None:
                return

            panel = await self.api.get_selfrole_panel(
                str(payload.guild_id), str(payload.message_id)
            )
            if not panel:
                return

            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return

            member = guild.get_member(payload.user_id)
            if member is None:
                return

            emoji_str = str(payload.emoji)
            roles_map: Dict[str, int] = panel.get("roles", {})
            role_id = roles_map.get(emoji_str)
            if not role_id:
                return

            role = guild.get_role(int(role_id))
            if role is None:
                return

            await self._enqueue_role_change(
                guild.id,
                member.id,
                "remove",
                [role.id],
                payload.channel_id,
            )

        except Exception:
            logger.exception("on_raw_reaction_remove error")


async def setup(bot: commands.Bot):
    await bot.add_cog(SelfRolesCog(bot))
