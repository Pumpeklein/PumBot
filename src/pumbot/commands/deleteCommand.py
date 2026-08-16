from __future__ import annotations

from typing import List

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger

ALLOWED_ROLES = {"Admin", "Team", "Twitch Moderator", "Discord Moderator"}
DELETE_CHANNEL_TYPES = (discord.TextChannel, discord.VoiceChannel)
BULK_DELETE_CHUNK = 100


def is_delete_staff(member: discord.Member) -> bool:
    try:
        if member.guild_permissions.administrator:
            return True
        return any(role.name in ALLOWED_ROLES for role in member.roles)
    except Exception:
        logger.exception("is_delete_staff error")
        return False


class DeleteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    delete_group = app_commands.Group(
        name="delete",
        description="Nachrichten löschen (Staff).",
    )

    @delete_group.command(
        name="clear", description="Löscht eine bestimmte Anzahl Nachrichten im Channel."
    )
    @app_commands.describe(amount="Anzahl (1-200)")
    async def clear(self, interaction: discord.Interaction, amount: int):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Konnte deine Mitgliedsdaten nicht lesen.", ephemeral=True
            )
            return

        if not is_delete_staff(member) or not member.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, DELETE_CHANNEL_TYPES):
            await interaction.response.send_message(
                "Dieser Befehl kann nur in Text- oder Voice-Channels verwendet werden.",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message(
                "Die Anzahl muss größer als 0 sein.", ephemeral=True
            )
            return

        if amount > 200:
            await interaction.response.send_message(
                "Maximal 200 Nachrichten auf einmal löschen.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            deleted = await channel.purge(limit=amount)
        except discord.Forbidden:
            await interaction.followup.send(
                "Ich habe keine Berechtigung, Nachrichten zu löschen.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            logger.exception("clear purge HTTPException: %r", e)
            await interaction.followup.send(
                "Beim Löschen der Nachrichten ist ein Fehler aufgetreten.",
                ephemeral=True,
            )
            return
        except Exception as e:
            logger.exception("clear purge unexpected error: %r", e)
            await interaction.followup.send(
                "Beim Löschen der Nachrichten ist ein unerwarteter Fehler aufgetreten.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ {len(deleted)} Nachricht(en) gelöscht.", ephemeral=True
        )

    @delete_group.command(
        name="clearuser", description="Löscht Nachrichten von einem bestimmten Nutzer."
    )
    @app_commands.describe(user="User", amount="Anzahl (1-200)")
    async def clear_user(
        self, interaction: discord.Interaction, user: discord.Member, amount: int
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Dieser Befehl kann nur auf einem Server verwendet werden.",
                ephemeral=True,
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Konnte deine Mitgliedsdaten nicht lesen.", ephemeral=True
            )
            return

        if not is_delete_staff(member) or not member.guild_permissions.manage_messages:
            await interaction.response.send_message(
                "Du hast keine Berechtigung, diesen Befehl zu nutzen.", ephemeral=True
            )
            return

        channel = interaction.channel
        if not isinstance(channel, DELETE_CHANNEL_TYPES):
            await interaction.response.send_message(
                "Dieser Befehl kann nur in Text- oder Voice-Channels verwendet werden.",
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message(
                "Die Anzahl muss größer als 0 sein.", ephemeral=True
            )
            return

        if amount > 200:
            await interaction.response.send_message(
                "Maximal 200 Nachrichten auf einmal löschen.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        to_delete: List[discord.Message] = []

        try:
            async for msg in channel.history(limit=1000, oldest_first=False):
                if msg.author.id == user.id:
                    to_delete.append(msg)
                    if len(to_delete) >= amount:
                        break
        except discord.Forbidden:
            await interaction.followup.send(
                "Ich habe keine Berechtigung, Channel-History zu lesen.", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            logger.exception("clear_user history HTTPException: %r", e)
            await interaction.followup.send(
                "Beim Lesen der Nachrichten ist ein Fehler aufgetreten.", ephemeral=True
            )
            return
        except Exception as e:
            logger.exception("clear_user history unexpected error: %r", e)
            await interaction.followup.send(
                "Beim Lesen der Nachrichten ist ein unerwarteter Fehler aufgetreten.",
                ephemeral=True,
            )
            return

        if not to_delete:
            await interaction.followup.send(
                "Es wurden keine passenden Nachrichten gefunden.", ephemeral=True
            )
            return

        # Discord erlaubt maximal 100 Nachrichten pro Bulk-Delete.
        bulk_deleted = 0
        leftovers: List[discord.Message] = []
        for start in range(0, len(to_delete), BULK_DELETE_CHUNK):
            chunk = to_delete[start : start + BULK_DELETE_CHUNK]
            try:
                await channel.delete_messages(chunk)
                bulk_deleted += len(chunk)
            except (discord.HTTPException, discord.ClientException) as e:
                logger.exception("clear_user bulk delete failed: %r", e)
                leftovers.extend(chunk)

        if not leftovers:
            await interaction.followup.send(
                f"✅ {bulk_deleted} Nachricht(en) von {user.mention} gelöscht.",
                ephemeral=True,
            )
            return

        deleted_count = 0
        for m in leftovers:
            try:
                await m.delete()
                deleted_count += 1
            except discord.HTTPException:
                pass
            except Exception:
                logger.exception("clear_user single delete unexpected error")

        await interaction.followup.send(
            f"{bulk_deleted + deleted_count} von {len(to_delete)} Nachricht(en) gelöscht. "
            f"Nachrichten, die älter als 14 Tage sind, kann Discord nur einzeln entfernen.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DeleteCog(bot))
