from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Iterable

import discord
from discord import app_commands
from discord.ext import commands

from src.pumbot.bot import logger


TEAM_ROLES = {
    "Admin",
    "Team",
    "Twitch Moderator",
    "Discord Moderator",
    "Twitch Moderation",
    "Discord Moderation",
}

HELP_LINKS: List[Tuple[str, str, str]] = [
    ("Instagram", "https://www.instagram.com/pumpeklein", "📸"),
    ("Discord", "https://discord.gg/TyYWzV6thQ", "💬"),
    ("Socials", "https://guns.lol/pumpeklein", "🌐"),
]


def is_team_member(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return any(r.name in TEAM_ROLES for r in member.roles)


def _iter_all_app_commands(
    tree: app_commands.CommandTree,
) -> List[app_commands.Command]:
    out: List[app_commands.Command] = []
    for cmd in tree.get_commands():
        out.append(cmd)
        if isinstance(cmd, app_commands.Group):
            out.extend(list(cmd.walk_commands()))
    return out


def _qualified_name(cmd: app_commands.Command) -> str:
    parts: List[str] = []
    cur: Optional[app_commands.Group] = getattr(cmd, "parent", None)
    while cur is not None:
        parts.append(cur.name)
        cur = getattr(cur, "parent", None)
    parts.reverse()
    parts.append(cmd.name)
    return " ".join(parts)


def _top_group_name(cmd: app_commands.Command) -> str:
    cur = cmd
    parent = getattr(cur, "parent", None)
    while parent is not None:
        cur = parent
        parent = getattr(cur, "parent", None)
    return getattr(cur, "name", "other") or "other"


def _split_lines_into_fields(
    lines: List[str],
    *,
    base_field_name: str,
    max_len: int = 1024,
) -> List[Tuple[str, str]]:
    if not lines:
        return [(base_field_name, "Keine Einträge gefunden.")]

    fields: List[Tuple[str, str]] = []
    buf: List[str] = []
    cur_len = 0
    idx = 1

    for line in lines:
        add_len = len(line) + (1 if buf else 0)
        if cur_len + add_len > max_len:
            fields.append((f"{base_field_name} ({idx})", "\n".join(buf)[:max_len]))
            idx += 1
            buf = [line]
            cur_len = len(line)
        else:
            buf.append(line)
            cur_len += add_len

    if buf:
        fields.append(
            (
                f"{base_field_name} ({idx})" if idx > 1 else base_field_name,
                "\n".join(buf)[:max_len],
            )
        )

    return fields


async def send_or_edit(
    interaction: discord.Interaction,
    *,
    content: Optional[str],
    embed: discord.Embed,
    view: Optional[discord.ui.View],
    public: bool,
    edit: bool = False,
) -> None:
    ephemeral = not public

    if edit:
        try:
            await interaction.response.edit_message(
                content=content, embed=embed, view=view
            )
            return
        except discord.InteractionResponded:
            await interaction.followup.send(
                content=content, embed=embed, view=view, ephemeral=ephemeral
            )
            return

    try:
        await interaction.response.send_message(
            content=content, embed=embed, view=view, ephemeral=ephemeral
        )
    except discord.InteractionResponded:
        await interaction.followup.send(
            content=content, embed=embed, view=view, ephemeral=ephemeral
        )


class CategoryDef:
    def __init__(
        self, key: str, label: str, desc: str, emoji: str, groups: Iterable[str]
    ):
        self.key = key
        self.label = label
        self.desc = desc
        self.emoji = emoji
        self.groups = {g.lower() for g in groups}


SUBGROUP_LABELS: Dict[str, Tuple[str, str]] = {
    "ticket": ("Tickets", "🎫"),
    "delete": ("Nachrichten / Cleanup", "🧹"),
    "usermanagement": ("User / Moderation", "🛡️"),
    "announce": ("Announcements", "📢"),
    "twitch_announce": ("Twitch Announcements", "📢"),
    "logs": ("Logs", "🧾"),
    "birthday": ("Geburtstage", "🎂"),
    "counting": ("Counting", "🔢"),
    "serverstats": ("Server Stats", "📊"),
    "server_stats": ("Server Stats", "📊"),
    "stats": ("Server Stats", "📊"),
    "selfroles": ("Selfroles", "🎭"),
    "other": ("Andere", "⚙️"),
}

MOD_GROUPS = {
    "ticket",
    "delete",
    "usermanagement",
    "announce",
    "twitch_announce",
    "logs",
}

CATEGORIES: List[CategoryDef] = [
    CategoryDef(
        key="team",
        label="Server Team",
        desc="Alles für Team & Moderation: Tickets, Verwarnungen, Timeouts, Cleanup, Announcements, Logs.",
        emoji="🛡️",
        groups=MOD_GROUPS,
    ),
    CategoryDef(
        key="logs",
        label="Logs",
        desc="Log-System konfigurieren, Channels setzen und testen.",
        emoji="🧾",
        groups={"logs"},
    ),
    CategoryDef(
        key="stats",
        label="Server Stats",
        desc="Statistiken, Übersichten und Server-Status-Infos.",
        emoji="📊",
        groups={"serverstats", "server_stats", "stats"},
    ),
    CategoryDef(
        key="birthdays",
        label="Geburtstage",
        desc="Geburtstage eintragen, anzeigen und Channel für Gratulationen verwalten.",
        emoji="🎂",
        groups={"birthday", "geburtstage"},
    ),
    CategoryDef(
        key="counting",
        label="Counting",
        desc="Counting-Spiel: Setup, Regeln und Verwaltung.",
        emoji="🔢",
        groups={"counting"},
    ),
    CategoryDef(
        key="selfroles",
        label="Selfroles",
        desc="Selfrole-Panels erstellen & bearbeiten, Rollen per Reaktion verwalten.",
        emoji="🎭",
        groups={"selfroles"},
    ),
    CategoryDef(
        key="other",
        label="Andere",
        desc="Sonstige Commands, die in keine Kategorie fallen.",
        emoji="⚙️",
        groups=set(),
    ),
]


def _category_keys_for_command(cmd: app_commands.Command) -> List[str]:
    top = _top_group_name(cmd).lower()

    keys: List[str] = []

    for cat in CATEGORIES:
        if cat.key == "other":
            continue
        if top in cat.groups:
            keys.append(cat.key)

    if top in MOD_GROUPS and "team" not in keys:
        keys.append("team")

    if not keys:
        keys.append("other")

    return keys


def _subgroup_key(cmd: app_commands.Command) -> str:
    top = _top_group_name(cmd).lower()
    if top in {"serverstats", "server_stats", "stats"}:
        return "serverstats"
    if top in {"geburtstage"}:
        return "birthday"
    return top if top else "other"


def _subgroup_title(subkey: str) -> Tuple[str, str]:
    if subkey in SUBGROUP_LABELS:
        return SUBGROUP_LABELS[subkey]
    return (subkey.capitalize(), "⚙️")


def _build_category_embed(
    *,
    bot: commands.Bot,
    category: CategoryDef,
) -> discord.Embed:
    all_cmds = [
        c
        for c in _iter_all_app_commands(bot.tree)
        if not isinstance(c, app_commands.Group)
    ]

    filtered: List[app_commands.Command] = []
    for c in all_cmds:
        if category.key in _category_keys_for_command(c):
            filtered.append(c)

    filtered.sort(key=lambda x: _qualified_name(x).lower())

    embed = discord.Embed(
        title=f"{category.emoji} Hilfe – {category.label}",
        description=category.desc,
        color=discord.Color.blurple(),
    )

    grouped: Dict[str, List[app_commands.Command]] = {}
    for c in filtered:
        sg = _subgroup_key(c)
        grouped.setdefault(sg, []).append(c)

    preferred_order = [
        "usermanagement",
        "ticket",
        "delete",
        "announce",
        "twitch_announce",
        "logs",
        "birthday",
        "serverstats",
        "counting",
        "selfroles",
        "other",
    ]
    order_map = {k: i for i, k in enumerate(preferred_order)}
    subgroup_keys = sorted(grouped.keys(), key=lambda k: order_map.get(k, 999))

    for sg in subgroup_keys:
        cmds = grouped[sg]
        title, emoji = _subgroup_title(sg)

        lines: List[str] = []
        for c in cmds:
            qn = _qualified_name(c)
            desc = (c.description or "Keine Beschreibung verfügbar.").strip()
            lines.append(f"• **/{qn}** – {desc}")

        field_name = f"{emoji} {title}"
        for name, value in _split_lines_into_fields(lines, base_field_name=field_name):
            embed.add_field(name=name, value=value, inline=False)

    return embed


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, *, bot: commands.Bot):
        self.bot = bot
        options: List[discord.SelectOption] = [
            discord.SelectOption(
                label=c.label,
                description=c.desc[:100],
                emoji=c.emoji,
                value=c.key,
            )
            for c in CATEGORIES[:25]
        ]

        super().__init__(
            placeholder="Wähle eine Kategorie",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            selected_key = self.values[0]
            cat = next((c for c in CATEGORIES if c.key == selected_key), None)
            if cat is None:
                await interaction.response.send_message(
                    "Kategorie nicht gefunden.", ephemeral=True
                )
                return

            embed = _build_category_embed(bot=self.bot, category=cat)
            await interaction.response.edit_message(embed=embed, view=self.view)

        except Exception:
            logger.exception("HelpCategorySelect callback error")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Fehler beim Laden der Kategorie.", ephemeral=True
                )


class HelpView(discord.ui.View):
    def __init__(self, *, bot: commands.Bot):
        super().__init__(timeout=180)
        self.add_item(HelpCategorySelect(bot=bot))

        for label, url, emoji in HELP_LINKS:
            self.add_item(
                discord.ui.Button(
                    label=label,
                    url=url,
                    style=discord.ButtonStyle.link,
                    emoji=emoji,
                )
            )


def _command_detail_embed(
    cmd: app_commands.Command, *, title_prefix: str
) -> discord.Embed:
    qn = _qualified_name(cmd)
    desc = (cmd.description or "Keine Beschreibung verfügbar.").strip()

    embed = discord.Embed(
        title=f"{title_prefix} /{qn}",
        description=desc,
        color=discord.Color.blurple(),
    )

    params = getattr(cmd, "parameters", None)
    if params:
        plines: List[str] = []
        for p in params:
            pname = getattr(p, "name", "")
            preq = getattr(p, "required", False)
            pdesc = getattr(p, "description", "") or ""
            req = "Pflicht" if preq else "Optional"
            plines.append(f"• **{pname}** ({req}) – {pdesc}".strip())

        for name, value in _split_lines_into_fields(
            plines, base_field_name="🧾 Parameter"
        ):
            embed.add_field(name=name, value=value, inline=False)

    return embed


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _autocomplete_commands(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        current_l = (current or "").lower()
        out: List[app_commands.Choice[str]] = []

        cmds = [
            c
            for c in _iter_all_app_commands(self.bot.tree)
            if not isinstance(c, app_commands.Group)
        ]
        cmds.sort(key=lambda x: _qualified_name(x).lower())

        for c in cmds:
            qn = _qualified_name(c)
            if current_l in qn.lower():
                out.append(app_commands.Choice(name=f"/{qn}", value=qn))
            if len(out) >= 25:
                break

        return out

    @app_commands.command(
        name="help",
        description="Zeigt Hilfe mit Kategorien oder Details zu einem Command.",
    )
    @app_commands.describe(
        user="Optional: Person, die gepingt werden soll",
        command="Optional: Command-Name, z.B. 'ticket close'",
        sichtbar="Nur Team: öffentlich posten (sonst ephemer)",
    )
    async def help_cmd(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        command: Optional[str] = None,
        sichtbar: Optional[bool] = False,
    ):
        try:
            public = bool(sichtbar)
            if public:
                if (
                    not interaction.guild
                    or not isinstance(interaction.user, discord.Member)
                    or not is_team_member(interaction.user)
                ):
                    await interaction.response.send_message(
                        "Öffentliche Hilfe dürfen nur Teamler posten.", ephemeral=True
                    )
                    return

            ping_content = user.mention if user else None
            view = HelpView(bot=self.bot)

            if command:
                cmd_name = command.strip().lstrip("/")
                target: Optional[app_commands.Command] = None

                for c in _iter_all_app_commands(self.bot.tree):
                    if isinstance(c, app_commands.Group):
                        continue
                    if _qualified_name(c).lower() == cmd_name.lower():
                        target = c
                        break

                if target is None:
                    await interaction.response.send_message(
                        "Command nicht gefunden.", ephemeral=True
                    )
                    return

                embed = _command_detail_embed(target, title_prefix="❓ Hilfe –")
                await send_or_edit(
                    interaction,
                    content=ping_content,
                    embed=embed,
                    view=view,
                    public=public,
                    edit=False,
                )
                return

            embed = discord.Embed(
                title="📚 Bot Hilfe",
                description="Wähle unten eine Kategorie oder nutze `/help command:<name>`.",
                color=discord.Color.blurple(),
            )

            all_cmds = [
                c
                for c in _iter_all_app_commands(self.bot.tree)
                if not isinstance(c, app_commands.Group)
            ]
            embed.set_footer(text=f"Gesamt: {len(all_cmds)} Slash-Commands")

            await send_or_edit(
                interaction,
                content=ping_content,
                embed=embed,
                view=view,
                public=public,
                edit=False,
            )

        except Exception:
            logger.exception("help_cmd error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Fehler beim Anzeigen der Hilfe.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Fehler beim Anzeigen der Hilfe.", ephemeral=True
                    )
            except Exception:
                logger.exception("help_cmd followup error")

    @app_commands.command(
        name="faq", description="FAQ / Erklärung zu Commands (für alle Slash-Commands)."
    )
    @app_commands.describe(
        user="Optional: Person, die gepingt werden soll",
        command="Optional: Command-Name, z.B. 'counting setchannel'",
        sichtbar="Nur Team: öffentlich posten (sonst ephemer)",
    )
    async def faq_cmd(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        command: Optional[str] = None,
        sichtbar: Optional[bool] = False,
    ):
        try:
            public = bool(sichtbar)
            if public:
                if (
                    not interaction.guild
                    or not isinstance(interaction.user, discord.Member)
                    or not is_team_member(interaction.user)
                ):
                    await interaction.response.send_message(
                        "Öffentliche FAQ dürfen nur Teamler posten.", ephemeral=True
                    )
                    return

            ping_content = user.mention if user else None

            if command:
                cmd_name = command.strip().lstrip("/")
                target: Optional[app_commands.Command] = None

                for c in _iter_all_app_commands(self.bot.tree):
                    if isinstance(c, app_commands.Group):
                        continue
                    if _qualified_name(c).lower() == cmd_name.lower():
                        target = c
                        break

                if target is None:
                    await interaction.response.send_message(
                        "Command nicht gefunden.", ephemeral=True
                    )
                    return

                embed = _command_detail_embed(target, title_prefix="📌 FAQ –")
                await send_or_edit(
                    interaction,
                    content=ping_content,
                    embed=embed,
                    view=None,
                    public=public,
                    edit=False,
                )
                return

            embed = discord.Embed(
                title="📌 FAQ",
                description="Nutze `/faq command:<name>` um eine Erklärung zu einem Command zu bekommen.",
                color=discord.Color.blurple(),
            )

            cmds = [
                c
                for c in _iter_all_app_commands(self.bot.tree)
                if not isinstance(c, app_commands.Group)
            ]
            cmds.sort(key=lambda x: _qualified_name(x).lower())

            lines = [
                f"• **/{_qualified_name(c)}** – {(c.description or 'Keine Beschreibung verfügbar.').strip()}"
                for c in cmds
            ]
            for name, value in _split_lines_into_fields(
                lines, base_field_name="📌 Commands"
            ):
                embed.add_field(name=name, value=value, inline=False)

            await send_or_edit(
                interaction,
                content=ping_content,
                embed=embed,
                view=None,
                public=public,
                edit=False,
            )

        except Exception:
            logger.exception("faq_cmd error")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "Fehler beim Anzeigen der FAQ.", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "Fehler beim Anzeigen der FAQ.", ephemeral=True
                    )
            except Exception:
                logger.exception("faq_cmd followup error")


async def setup(bot: commands.Bot):
    try:
        cog = HelpCog(bot)
        await bot.add_cog(cog)

        try:
            help_command = bot.tree.get_command("help")
            if help_command:
                help_command.autocomplete("command")(cog._autocomplete_commands)
        except Exception:
            logger.exception("help autocomplete bind error")

        try:
            faq_command = bot.tree.get_command("faq")
            if faq_command:
                faq_command.autocomplete("command")(cog._autocomplete_commands)
        except Exception:
            logger.exception("faq autocomplete bind error")

        logger.info("HelpCog (Slash) geladen.")
    except Exception:
        logger.exception("setup HelpCog error")
