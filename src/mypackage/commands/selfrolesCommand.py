from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from src.mypackage.bot import logger

DATA_DIR = Path("data")
SELFROLES_FILE = DATA_DIR / "selfroles.json"

SELFROLE_STAFF_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}


def is_selfrole_staff(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name in SELFROLE_STAFF_ROLES for r in member.roles)


def load_selfroles() -> Dict[str, Any]:
    if SELFROLES_FILE.exists():
        try:
            with SELFROLES_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
        except Exception:
            logger.exception("Fehler beim Laden der Selfroles-Datei")
            return {}
    return {}


def save_selfroles(data: Dict[str, Any]) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with SELFROLES_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception:
        logger.exception("Fehler beim Speichern der Selfroles-Datei")


class SelfRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
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
        rollen_und_emojis="Paare im Format: @Rolle 😀 @Rolle 😎 ...",
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
                "Ich konnte keine gültigen Rollen/Emoji-Paare erkennen. Beispiel: `@Minecraft ⛏️ @Valorant 🎯`",
                ephemeral=True,
            )
            return

        description = (
            "Reagiere, um Rollen zu erhalten oder zu entfernen.\n\n" + "\n".join(lines)
        )

        embed = discord.Embed(
            title=f"{titel} (Limit: {limit if limit > 0 else '∞'})",
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

        data = load_selfroles()
        g_id = str(guild.id)
        m_id = str(message.id)

        if g_id not in data:
            data[g_id] = {}

        data[g_id][m_id] = {
            "max_roles": limit,
            "title": titel,
            "roles": roles_map,
            "channel_id": message.channel.id,
        }

        save_selfroles(data)

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

        data = load_selfroles()
        g_id = str(interaction.guild.id)
        g_data = data.get(g_id)
        if not g_data:
            await interaction.response.send_message(
                "Für diesen Server existieren noch keine Self-Role Panels.",
                ephemeral=True,
            )
            return

        panel_title_lower = panel_titel.lower()
        target_msg_id: int | None = None
        config: Dict[str, Any] | None = None

        for msg_id_str, cfg in g_data.items():
            if not isinstance(cfg, dict):
                continue
            if cfg.get("title", "").lower() == panel_title_lower:
                target_msg_id = int(msg_id_str)
                config = cfg
                break

        if target_msg_id is None or config is None:
            await interaction.response.send_message(
                f"Kein Self-Role Panel mit dem Titel **{panel_titel}** gefunden.",
                ephemeral=True,
            )
            return

        channel_id = config.get("channel_id")
        if channel_id is None:
            await interaction.response.send_message(
                "Für dieses Self-Role Panel ist kein Channel gespeichert.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Der Kanal für dieses Self-Role Panel konnte nicht gefunden werden.",
                ephemeral=True,
            )
            return

        try:
            message = await channel.fetch_message(target_msg_id)
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

        roles_map: Dict[str, int] = config.get("roles", {})
        aktion = aktion.lower()
        emoji_key = emoji

        if aktion == "add":
            if emoji_key in roles_map:
                await interaction.response.send_message(
                    "Für dieses Emoji ist bereits eine Rolle in diesem Panel eingetragen.",
                    ephemeral=True,
                )
                return

            roles_map[emoji_key] = rolle.id
            config["roles"] = roles_map
            g_data[str(target_msg_id)] = config
            data[g_id] = g_data
            save_selfroles(data)

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

            if existing_role_id != rolle.id:
                await interaction.response.send_message(
                    "Die Kombination aus Rolle und Emoji passt nicht zu diesem Panel.",
                    ephemeral=True,
                )
                return

            roles_map.pop(emoji_key, None)
            config["roles"] = roles_map
            g_data[str(target_msg_id)] = config
            data[g_id] = g_data
            save_selfroles(data)

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

            data = load_selfroles()
            g_id = str(payload.guild_id)
            m_id = str(payload.message_id)

            g_data = data.get(g_id)
            if not g_data:
                return

            config = g_data.get(m_id)
            if not config or not isinstance(config, dict):
                return

            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return

            member = guild.get_member(payload.user_id)
            if member is None:
                return

            emoji_str = str(payload.emoji)
            roles_map: Dict[str, int] = config.get("roles", {})
            role_id = roles_map.get(emoji_str)
            if not role_id:
                return

            role = guild.get_role(role_id)
            if role is None:
                return

            max_roles = int(config.get("max_roles", 0) or 0)
            if max_roles > 0:
                current_roles = []
                for _, r_id in roles_map.items():
                    r = guild.get_role(r_id)
                    if r and r in member.roles:
                        current_roles.append(r)

                if len(current_roles) >= max_roles:
                    if max_roles == 1:
                        await self._enqueue_role_change(
                            guild.id,
                            member.id,
                            "remove",
                            [r.id for r in current_roles],
                            payload.channel_id,
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

            data = load_selfroles()
            g_id = str(payload.guild_id)
            m_id = str(payload.message_id)

            g_data = data.get(g_id)
            if not g_data:
                return

            config = g_data.get(m_id)
            if not config or not isinstance(config, dict):
                return

            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return

            member = guild.get_member(payload.user_id)
            if member is None:
                return

            emoji_str = str(payload.emoji)
            roles_map: Dict[str, int] = config.get("roles", {})
            role_id = roles_map.get(emoji_str)
            if not role_id:
                return

            role = guild.get_role(role_id)
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
