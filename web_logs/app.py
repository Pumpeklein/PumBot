from __future__ import annotations

import asyncio
import json
import re
import subprocess
from datetime import datetime, timezone
from functools import wraps
from html import escape
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv()

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

try:
    from .config import Config, DEFAULT_GUILD_ID, ensure_dirs
    from .db import (
        ALL_PERMISSIONS,
        COMMAND_PERMISSION_GROUPS,
        PERMISSION_GROUPS,
        PERMISSION_LABELS,
        permission_label,
        list_role_members,
        count_role_members,
        get_role,
        get_selfrole_role_ids,
        add_auto_publisher_channel,
        add_close_reason,
        add_selfrole_mapping,
        add_ticket_message,
        add_warning,
        count_birthdays,
        count_birthdays_in_month,
        get_upcoming_birthdays,
        count_counting_leaderboard,
        count_guild_members,
        count_discord_log_entries,
        count_guild_message_history,
        count_guild_messages,
        count_tickets,
        count_warnings,
        clear_warnings,
        create_role,
        create_selfrole_panel,
        delete_birthday,
        delete_bot_message,
        delete_close_reason,
        delete_config,
        delete_role,
        delete_selfrole_panel,
        get_all_log_channels,
        get_channel_names,
        get_all_selfrole_panels,
        get_auto_publisher_channels,
        get_birthday,
        get_birthdays_panel_guild_id,
        list_bot_messages,
        get_birthdays,
        get_birthdays_today,
        get_config,
        get_counting,
        get_counting_leaderboard,
        get_counting_stats,
        get_guild_member,
        get_guild_member_name_history,
        get_discord_log_overview,
        get_guild_members_panel_guild_id,
        get_guild_message_chart_data,
        get_guild_message_overview,
        list_user_connections,
        get_log_channel,
        get_selfrole_panel,
        get_server_stats,
        get_ticket,
        get_ticket_messages,
        get_ticket_stats_for_user,
        get_twitch_config,
        get_user_by_discord_id,
        get_warnings,
        get_user_channel_message_stats,
        get_user_message_stats,
        init_db,
        insert_ticket_log,
        list_all_warnings,
        list_close_reasons,
        list_guild_members,
        list_discord_log_entries,
        list_guild_message_history,
        list_guild_messages,
        list_message_filter_channels,
        list_message_filter_users,
        count_tickets_for_user,
        list_logs_for_ticket,
        list_roles,
        list_tickets,
        list_tickets_for_user,
        mark_birthday_congrats,
        mark_guild_member_left,
        remove_auto_publisher_channel,
        remove_log_channel,
        remove_selfrole_mapping,
        remove_twitch_config,
        remove_warning,
        parse_member_roles,
        set_birthday,
        set_config,
        set_counting,
        set_counting_stats,
        set_log_channel,
        set_server_stats,
        set_twitch_config,
        sync_guild_members,
        mark_guild_message_deleted,
        update_guild_member_profile_fields,
        update_guild_member_roles,
        upsert_discord_log_entry,
        upsert_guild_member,
        upsert_bot_message,
        upsert_guild_message,
        upsert_guild_messages,
        update_close_reason,
        update_role,
        upsert_ticket,
    )
    from .auth import (
        current_user,
        discord_login_url,
        has_permission,
        login_required,
        login_user_from_oauth,
        permission_required,
        refresh_current_user_permissions,
    )
    from .token_utils import verify_transcript_token
    from .datetime_format import format_berlin_date, format_berlin_datetime
except ImportError:
    from config import Config, DEFAULT_GUILD_ID, ensure_dirs
    from db import (
        ALL_PERMISSIONS,
        COMMAND_PERMISSION_GROUPS,
        PERMISSION_GROUPS,
        PERMISSION_LABELS,
        permission_label,
        list_role_members,
        count_role_members,
        get_role,
        get_selfrole_role_ids,
        add_auto_publisher_channel,
        add_close_reason,
        add_selfrole_mapping,
        add_ticket_message,
        add_warning,
        count_birthdays,
        count_birthdays_in_month,
        get_upcoming_birthdays,
        count_counting_leaderboard,
        count_guild_members,
        count_discord_log_entries,
        count_guild_message_history,
        count_guild_messages,
        count_tickets,
        count_warnings,
        clear_warnings,
        create_role,
        create_selfrole_panel,
        delete_birthday,
        delete_bot_message,
        delete_close_reason,
        delete_config,
        delete_role,
        delete_selfrole_panel,
        get_all_log_channels,
        get_channel_names,
        get_all_selfrole_panels,
        get_auto_publisher_channels,
        get_birthday,
        get_birthdays_panel_guild_id,
        list_bot_messages,
        get_birthdays,
        get_birthdays_today,
        get_config,
        get_counting,
        get_counting_leaderboard,
        get_counting_stats,
        get_guild_member,
        get_guild_member_name_history,
        get_discord_log_overview,
        get_guild_members_panel_guild_id,
        get_guild_message_chart_data,
        get_guild_message_overview,
        list_user_connections,
        get_log_channel,
        get_selfrole_panel,
        get_server_stats,
        get_ticket,
        get_ticket_messages,
        get_ticket_stats_for_user,
        get_twitch_config,
        get_user_by_discord_id,
        get_warnings,
        get_user_channel_message_stats,
        get_user_message_stats,
        init_db,
        insert_ticket_log,
        list_all_warnings,
        list_close_reasons,
        list_guild_members,
        list_discord_log_entries,
        list_guild_message_history,
        list_guild_messages,
        list_message_filter_channels,
        list_message_filter_users,
        count_tickets_for_user,
        list_logs_for_ticket,
        list_roles,
        list_tickets,
        list_tickets_for_user,
        mark_birthday_congrats,
        mark_guild_member_left,
        remove_auto_publisher_channel,
        remove_log_channel,
        remove_selfrole_mapping,
        remove_twitch_config,
        remove_warning,
        parse_member_roles,
        set_birthday,
        set_config,
        set_counting,
        set_counting_stats,
        set_log_channel,
        set_server_stats,
        set_twitch_config,
        sync_guild_members,
        mark_guild_message_deleted,
        update_guild_member_profile_fields,
        update_guild_member_roles,
        upsert_discord_log_entry,
        upsert_guild_member,
        upsert_bot_message,
        upsert_guild_message,
        upsert_guild_messages,
        update_close_reason,
        update_role,
        upsert_ticket,
    )
    from auth import (
        current_user,
        discord_login_url,
        has_permission,
        login_required,
        login_user_from_oauth,
        permission_required,
        refresh_current_user_permissions,
    )
    from token_utils import verify_transcript_token
    from datetime_format import format_berlin_date, format_berlin_datetime

ensure_dirs()

app = Flask(__name__)
app.secret_key = Config.FLASK_SECRET_KEY
app.jinja_env.filters["date_de"] = format_berlin_date
app.jinja_env.filters["datetime_de"] = format_berlin_datetime
app.jinja_env.filters["permission_label"] = permission_label
app.jinja_env.globals["PERMISSION_LABELS"] = PERMISSION_LABELS

init_db()

LOG_TYPES = [
    "voice_log",
    "user_log",
    "server_log",
    "message_log",
    "welcome_log",
    "team_change_log",
    "bot_change_log",
]

CHANGE_UPDATE_TYPES = {
    "team": {
        "title": "Team Änderungen",
        "singular": "Team Änderung",
        "log_type": "team_change_log",
        "view_permission": "team_updates.view",
        "send_permission": "team_updates.send",
        "active_page": "team_changes",
        "endpoint": "team_changes_page",
    },
    "bot": {
        "title": "Bot-Änderungen",
        "singular": "Bot-Änderung",
        "log_type": "bot_change_log",
        "view_permission": "bot_updates.view",
        "send_permission": "bot_updates.send",
        "active_page": "bot_changes",
        "endpoint": "bot_changes_page",
    },
}

TEAM_PING_ROLE_NAMES = {
    "admin",
    "team",
    "twitch moderator",
    "twitch moderation",
    "discord moderator",
    "discord moderation",
    "admin ticket",
}


def create_app() -> Flask:
    return app


@app.before_request
def _refresh_session_permissions():
    if request.endpoint in {
        "static",
        "login",
        "auth_discord",
        "auth_discord_callback",
        "logout",
    }:
        return None
    if "discord_id" not in session:
        return None
    if refresh_current_user_permissions():
        return None

    app.logger.warning(
        "Session permissions revoked for user %s on %s",
        session.get("discord_id"),
        request.path,
    )
    session.clear()
    if request.path.startswith("/panel-api/") or request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return redirect(url_for("login"))


def _ctx() -> dict:
    u = current_user()
    if not u:
        return {
            "username": None,
            "avatar": None,
            "permissions": set(),
            "discord_id": None,
        }
    return {
        "username": u["username"],
        "avatar": u.get("avatar"),
        "permissions": u["permissions"],
        "discord_id": str(u.get("discord_id") or "") or None,
    }


TICKET_CATEGORY_PERMISSIONS = {
    "discord": "tickets.discord.view",
    "twitch": "tickets.twitch.view",
    "general": "tickets.general.view",
    "admin": "tickets.admin.view",
}


def _allowed_ticket_categories(permissions: set[str]) -> set[str] | None:
    if "admin" in permissions:
        return None
    return {
        category
        for category, permission in TICKET_CATEGORY_PERMISSIONS.items()
        if permission in permissions
    }


def permission_any_required(*required_permissions: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user():
                return redirect(url_for("login"))
            if not any(has_permission(permission) for permission in required_permissions):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def _ticket_category_key(ticket: dict | None) -> str:
    value = str((ticket or {}).get("category") or "general").strip().lower()
    if "twitch" in value:
        return "twitch"
    if "discord" in value:
        return "discord"
    if "admin" in value:
        return "admin"
    return value or "general"


def _can_access_ticket(
    ticket: dict | None, permissions: set[str] | None = None
) -> bool:
    if not ticket:
        return False
    perms = (
        permissions
        if permissions is not None
        else (current_user() or {}).get("permissions", set())
    )
    allowed = _allowed_ticket_categories(set(perms))
    if allowed is None:
        return True
    return _ticket_category_key(ticket) in allowed


def _resolve_transcript_path(transcript_path: str) -> Path:
    path = Path(transcript_path)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parent / transcript_path).resolve()
    return path


def _render_transcript_html(data: dict) -> str:
    transcript_html = (data.get("transcript_html") or "").strip()
    if transcript_html:
        return _format_transcript_dates(transcript_html)
    transcript_text = data.get("transcript_text") or ""
    if transcript_text:
        return _format_transcript_dates(f"<pre>{escape(transcript_text)}</pre>")
    return ""


_TRANSCRIPT_DATETIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?"
)


def _format_transcript_dates(html: str) -> str:
    return _TRANSCRIPT_DATETIME_RE.sub(
        lambda m: format_berlin_datetime(m.group(0), fallback=m.group(0)),
        html,
    )


def _format_date_fields(rows: list[dict], *fields: str) -> list[dict]:
    formatted = []
    for row in rows:
        item = dict(row)
        for field in fields:
            if item.get(field):
                item[field] = format_berlin_datetime(item[field], fallback=item[field])
        formatted.append(item)
    return formatted


def _accent_color_hex(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.startswith("#"):
        return value
    try:
        color = int(value)
    except (TypeError, ValueError):
        return None
    return f"#{color & 0xFFFFFF:06x}"


def _extract_change_actor(content: str | None) -> str | None:
    if not content:
        return None
    match = re.search(r"^\*\*Von:\*\*\s*(.+)$", content, flags=re.MULTILINE)
    return match.group(1).strip()[:255] if match else None


def _split_log_content(content: str | None) -> tuple[str | None, str | None]:
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    if not lines:
        return None, None
    title = lines[0].strip("*` ")
    summary = "\n".join(lines[1:]).strip()
    return title or None, summary or None


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _resolve_display_name(
    user_id: str | int | None,
    cache: dict[str, str | None] | None = None,
    guild_id: str | None = None,
) -> str | None:
    if user_id in (None, ""):
        return None

    key = str(user_id)
    cache_key = f"{guild_id or DEFAULT_GUILD_ID}:{key}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    cached_member = get_guild_member(guild_id or DEFAULT_GUILD_ID, key)
    display_name = cached_member.get("display_name") if cached_member else None
    if not display_name:
        display_name = key

    if cache is not None:
        cache[cache_key] = display_name
    return display_name


def _member_profile(guild_id: str, user_id: str | int | None) -> dict:
    if user_id in (None, ""):
        return {
            "display_name": None,
            "avatar_url": None,
            "username": None,
            "status": None,
        }
    member = get_guild_member(guild_id, str(user_id))
    if not member:
        return {
            "display_name": str(user_id),
            "avatar_url": None,
            "username": None,
            "status": None,
        }
    return {
        "display_name": member.get("display_name")
        or member.get("username")
        or str(user_id),
        "avatar_url": member.get("avatar_url"),
        "username": member.get("username"),
        "status": member.get("status"),
    }


def _attach_member_profile(
    row: dict,
    guild_id: str,
    user_field: str,
    prefix: str = "user",
) -> dict:
    user_id = row.get(user_field)
    profile = _member_profile(guild_id, user_id)
    item = dict(row)
    item[f"{prefix}_display_name"] = profile["display_name"]
    item[f"{prefix}_avatar_url"] = profile["avatar_url"]
    item[f"{prefix}_username"] = profile["username"]
    item[f"{prefix}_status"] = profile["status"]
    item[f"{prefix}_detail_url"] = (
        url_for("user_detail_page", user_id=str(user_id), guild_id=guild_id)
        if user_id not in (None, "")
        else None
    )
    return item


def _attach_display_name(
    rows: list[dict],
    user_field: str,
    target_field: str = "display_name",
    cache: dict[str, str | None] | None = None,
    guild_id: str | None = None,
) -> list[dict]:
    local_cache = cache if cache is not None else {}
    enriched = []
    for row in rows:
        item = dict(row)
        item[target_field] = _resolve_display_name(
            item.get(user_field), local_cache, guild_id=guild_id
        )
        enriched.append(item)
    return enriched


def _format_stats_filter_users(rows: list[dict]) -> list[dict]:
    formatted = []
    for row in rows:
        item = dict(row)
        display_name = (
            item.get("display_name")
            or item.get("username")
            or item.get("oauth_username")
        )
        if not display_name:
            continue
        item["filter_label"] = display_name
        item["filter_subtitle"] = str(item["user_id"]) if item.get("user_id") else ""
        formatted.append(item)
    return formatted


def _active_panel_guild_id() -> str:
    requested_guild_id = (request.args.get("guild_id") or "").strip()
    if requested_guild_id:
        return requested_guild_id

    stored_guild_id = get_guild_members_panel_guild_id(DEFAULT_GUILD_ID)
    if stored_guild_id != DEFAULT_GUILD_ID or list_guild_members(
        stored_guild_id, limit=1
    ):
        return stored_guild_id

    bot = app.config.get("DISCORD_BOT")
    if bot and getattr(bot, "is_ready", lambda: False)():
        guilds = getattr(bot, "guilds", []) or []
        if guilds:
            return str(guilds[0].id)

    return stored_guild_id


def _pagination_args(default_page_size: int = 10) -> tuple[int, int, int]:
    page = request.args.get("page", 1, type=int) or 1
    page_size = (
        request.args.get("page_size", default_page_size, type=int) or default_page_size
    )
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    return page, page_size, offset


def _paginated_response(items: list[dict], total: int, page: int, page_size: int):
    return jsonify(
        {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, (total + page_size - 1) // page_size),
            },
        }
    )


def _run_bot_coro(coro):
    bot = app.config.get("DISCORD_BOT")
    if not bot or not bot.is_ready():
        if hasattr(coro, "close"):
            coro.close()
        return None, "Bot ist nicht verbunden."
    try:
        future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        return future.result(timeout=15), None
    except Exception as exc:
        return None, str(exc)


def _schedule_bot_coro(coro) -> str | None:
    bot = app.config.get("DISCORD_BOT")
    if not bot or not bot.is_ready():
        if hasattr(coro, "close"):
            coro.close()
        return "Bot ist nicht verbunden."
    try:
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
        return None
    except Exception as exc:
        return str(exc)


def _birthday_label(birthday: dict | None) -> str | None:
    if not birthday:
        return None
    try:
        day = int(birthday.get("day") or 0)
        month = int(birthday.get("month") or 0)
    except (TypeError, ValueError):
        return None
    if not day or not month:
        return None
    year = birthday.get("year")
    return f"{day:02d}.{month:02d}" + (f".{year}" if year else "")


def _trigger_discord_log_sync(guild_id: str) -> None:
    bot = app.config.get("DISCORD_BOT")
    if not bot or not bot.is_ready() or not hasattr(bot, "sync_log_channels"):
        return
    error = _schedule_bot_coro(bot.sync_log_channels(guild_id))
    if error:
        app.logger.warning("Discord log sync trigger failed: %s", error)


def _git_commit_summary(limit: int = 5) -> list[dict[str, str]]:
    limit = max(1, min(50, int(limit or 5)))
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"-n{limit}",
                "--date=short",
                "--pretty=format:%h%x1f%ad%x1f%an%x1f%s",
            ],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        app.logger.warning("Git summary failed: %s", exc)
        return []

    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        commit_hash, date, author, subject = parts
        commits.append(
            {
                "hash": commit_hash,
                "date": date,
                "author": author,
                "subject": subject,
            }
        )
    return commits


def _format_git_summary(commits: list[dict[str, str]]) -> str:
    if not commits:
        return "Keine Git-Einträge gefunden."
    lines = [f"Git-Zusammenfassung ({len(commits)} Einträge):"]
    for commit in commits:
        lines.append(
            f"- {commit['hash']} ({commit['date']}): {commit['subject']} [{commit['author']}]"
        )
    return "\n".join(lines)


def _selected_git_commits(all_commits: list[dict[str, str]], selected_hashes: list[str]) -> list[dict[str, str]]:
    selected = {str(commit_hash).strip() for commit_hash in selected_hashes if commit_hash}
    if not selected:
        return []
    return [commit for commit in all_commits if commit["hash"] in selected]


def _is_team_ping_role_name(name: str) -> bool:
    normalized = " ".join(str(name or "").strip().lower().split())
    return normalized in TEAM_PING_ROLE_NAMES


def _team_ping_role_options(guild_id: str) -> list[dict[str, str]]:
    by_id: dict[str, dict[str, str]] = {}
    for role in list_roles(guild_id):
        role_id = str(role.get("discord_role_id") or "").strip()
        role_name = str(role.get("role_name") or role_id)
        if role_id and _is_team_ping_role_name(role_name):
            by_id[role_id] = {
                "id": role_id,
                "name": role_name,
                "source": "Web Rolle",
            }
    for role in _live_discord_roles(guild_id):
        role_id = str(role.get("id") or "").strip()
        role_name = str(role.get("name") or role_id)
        if role_id and role_id not in by_id and _is_team_ping_role_name(role_name):
            by_id[role_id] = {
                "id": role_id,
                "name": role_name,
                "source": "Discord",
            }
    return sorted(by_id.values(), key=lambda role: role["name"].lower())


def _valid_ping_role_ids(guild_id: str, requested_role_ids: list[str]) -> list[str]:
    allowed = {role["id"] for role in _team_ping_role_options(guild_id)}
    result = []
    for role_id in requested_role_ids:
        role_id = str(role_id).strip()
        if role_id in allowed and role_id not in result:
            result.append(role_id)
    return result


async def _send_change_message(
    channel_id: int,
    change_label: str,
    author: str,
    content: str,
    git_summary: str | None = None,
    ping_role_ids: list[str] | None = None,
) -> object:
    import discord

    bot = app.config.get("DISCORD_BOT")
    channel = bot.get_channel(channel_id) if bot else None
    if channel is None and bot:
        channel = await bot.fetch_channel(channel_id)
    if channel is None or not hasattr(channel, "send"):
        raise RuntimeError(f"{change_label}-Channel nicht gefunden.")

    ping_line = " ".join(f"<@&{role_id}>" for role_id in (ping_role_ids or []))
    message = f"**{change_label}**\n**Von:** {author}"
    if ping_line:
        message = f"{ping_line}\n{message}"
    if content:
        message = f"{message}\n\n{content}"
    if git_summary:
        message = f"{message}\n\n```text\n{git_summary[:1500]}\n```"
    return await channel.send(
        message[:1900],
        allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
    )


def _role_dict(role, *, actor_member=None, bot_member=None) -> dict:
    actor_can_manage = _member_can_manage_role(actor_member, role)
    bot_can_manage = _member_can_manage_role(bot_member, role)
    manageable = (
        actor_can_manage
        and bot_can_manage
        and not getattr(role, "managed", False)
        and not getattr(role, "is_default", lambda: False)()
    )
    return {
        "id": str(role.id),
        "name": role.name,
        "position": role.position,
        "managed": role.managed,
        "color": str(role.color),
        "manageable": manageable,
        "blocked_reason": None
        if manageable
        else _role_blocked_reason(role, actor_member, bot_member),
    }


def _member_can_manage_role(member, role) -> bool:
    if member is None or role is None:
        return False
    if getattr(role, "is_default", lambda: False)():
        return False
    guild = getattr(role, "guild", None) or getattr(member, "guild", None)
    if guild and getattr(guild, "owner_id", None) == getattr(member, "id", None):
        return True
    top_role = getattr(member, "top_role", None)
    return bool(
        top_role and getattr(top_role, "position", 0) > getattr(role, "position", 0)
    )


def _role_blocked_reason(role, actor_member=None, bot_member=None) -> str:
    if getattr(role, "managed", False):
        return "Managed Rolle"
    if not _member_can_manage_role(actor_member, role):
        return "Über deiner höchsten Rolle"
    if not _member_can_manage_role(bot_member, role):
        return "Über der Bot-Rolle"
    return "Nicht verwaltbar"


def _live_role_context(guild_id: str):
    bot = app.config.get("DISCORD_BOT")
    if not bot or not bot.is_ready():
        return None, None, None
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return None, None, None
    user = current_user()
    actor_member = None
    if user and user.get("discord_id"):
        actor_member = guild.get_member(int(user["discord_id"]))
        if actor_member is None:
            role_ids = {str(role_id) for role_id in session.get("discord_roles", [])}
            actor_roles = [role for role in guild.roles if str(role.id) in role_ids]
            if actor_roles:
                actor_member = SimpleNamespace(
                    id=int(user["discord_id"]),
                    top_role=max(actor_roles, key=lambda role: role.position),
                    guild=guild,
                )
    bot_member = guild.me
    return guild, actor_member, bot_member


def _live_discord_roles(guild_id: str) -> list[dict]:
    guild, actor_member, bot_member = _live_role_context(guild_id)
    if not guild:
        return []
    return [
        _role_dict(role, actor_member=actor_member, bot_member=bot_member)
        for role in sorted(guild.roles, key=lambda r: r.position, reverse=True)
        if not getattr(role, "is_default", lambda: False)()
    ]


async def _discord_add_member_role(
    guild_id: str, user_id: str, role_id: str, actor_user_id: str | None
) -> list[dict]:
    bot = app.config.get("DISCORD_BOT")
    guild = bot.get_guild(int(guild_id)) if bot else None
    if guild is None:
        raise RuntimeError("Guild nicht gefunden.")
    member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
    role = guild.get_role(int(role_id))
    if role is None:
        raise RuntimeError("Rolle nicht gefunden.")
    actor = None
    if actor_user_id:
        actor = guild.get_member(int(actor_user_id)) or await guild.fetch_member(
            int(actor_user_id)
        )
    if not _member_can_manage_role(actor, role):
        raise RuntimeError(
            "Du kannst keine Rolle vergeben, die über deiner höchsten Rolle liegt."
        )
    if not _member_can_manage_role(guild.me, role):
        raise RuntimeError(
            "Der Bot kann diese Rolle wegen der Discord-Hierarchie nicht vergeben."
        )
    if getattr(role, "managed", False):
        raise RuntimeError("Managed Rollen können nicht manuell vergeben werden.")
    await member.add_roles(role, reason="Web Panel")
    return [
        {"id": str(role.id), "name": role.name}
        for role in sorted(member.roles, key=lambda r: r.position, reverse=True)
        if role.name != "@everyone"
    ]


async def _discord_remove_member_role(
    guild_id: str, user_id: str, role_id: str, actor_user_id: str | None
) -> list[dict]:
    bot = app.config.get("DISCORD_BOT")
    guild = bot.get_guild(int(guild_id)) if bot else None
    if guild is None:
        raise RuntimeError("Guild nicht gefunden.")
    member = guild.get_member(int(user_id)) or await guild.fetch_member(int(user_id))
    role = guild.get_role(int(role_id))
    if role is None:
        raise RuntimeError("Rolle nicht gefunden.")
    actor = None
    if actor_user_id:
        actor = guild.get_member(int(actor_user_id)) or await guild.fetch_member(
            int(actor_user_id)
        )
    if not _member_can_manage_role(actor, role):
        raise RuntimeError(
            "Du kannst keine Rolle entfernen, die über deiner höchsten Rolle liegt."
        )
    if not _member_can_manage_role(guild.me, role):
        raise RuntimeError(
            "Der Bot kann diese Rolle wegen der Discord-Hierarchie nicht entfernen."
        )
    if getattr(role, "managed", False):
        raise RuntimeError("Managed Rollen können nicht manuell entfernt werden.")
    await member.remove_roles(role, reason="Web Panel")
    return [
        {"id": str(role.id), "name": role.name}
        for role in sorted(member.roles, key=lambda r: r.position, reverse=True)
        if role.name != "@everyone"
    ]


async def _discord_create_role(
    guild_id: str, name: str, color_hex: str | None = None
) -> dict:
    import discord

    bot = app.config.get("DISCORD_BOT")
    guild = bot.get_guild(int(guild_id)) if bot else None
    if guild is None:
        raise RuntimeError("Guild nicht gefunden.")
    color_value = 0
    if color_hex:
        color_value = int(color_hex.strip().lstrip("#"), 16)
    role = await guild.create_role(
        name=name,
        colour=discord.Colour(color_value),
        reason="Web Panel",
    )
    return {"id": str(role.id), "name": role.name}


async def _discord_fetch_user_profile(user_id: str) -> dict:
    bot = app.config.get("DISCORD_BOT")
    if bot is None:
        raise RuntimeError("Bot ist nicht verbunden.")
    user = await bot.fetch_user(int(user_id))
    banner = getattr(user, "banner", None)
    accent_color = getattr(user, "accent_color", None)
    return {
        "banner_url": str(banner.url) if banner else None,
        "accent_color": int(accent_color.value) if accent_color else None,
        "locale": str(getattr(user, "locale", ""))
        if getattr(user, "locale", None)
        else None,
    }


# ---------------- API KEY SECURITY ----------------


def api_key_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = Config.LOG_API_KEY
        if not expected:
            return jsonify({"ok": False, "error": "server_not_configured"}), 500
        provided = request.headers.get("X-API-KEY")
        if provided != expected:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


# ---------------- AUTH ROUTES ----------------


@app.get("/login")
def login():
    if current_user():
        return redirect(url_for("tickets_page"))
    return render_template("login.html", discord_url=discord_login_url())


@app.get("/auth/discord")
def auth_discord():
    return redirect(discord_login_url())


@app.get("/auth/discord/callback")
def auth_discord_callback():
    code = request.args.get("code")
    if not code:
        return redirect(url_for("login"))
    success = login_user_from_oauth(code)
    if not success:
        return render_template(
            "login.html",
            discord_url=discord_login_url(),
            error="Login fehlgeschlagen. Stelle sicher, dass du eine verknüpfte Rolle auf dem Server hast.",
        )
    return redirect(url_for("tickets_page"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- WEB PAGES ----------------


@app.get("/")
def home():
    if not current_user():
        return redirect(url_for("login"))
    return redirect(url_for("tickets_page"))


@app.get("/tickets")
@login_required
def tickets_page():
    ctx = _ctx()
    q = request.args.get("q", "")
    status_filter = request.args.get("status", "all")
    if status_filter not in {"all", "open", "closed"}:
        status_filter = "all"
    categories = _allowed_ticket_categories(set(ctx["permissions"]))
    status_arg = status_filter if status_filter != "all" else None
    return render_template(
        "tickets.html",
        q=q,
        status=status_filter,
        total=count_tickets(q=q, categories=categories, status=status_arg),
        open_count=count_tickets(categories=categories, status="open"),
        closed_count=count_tickets(categories=categories, status="closed"),
        active_page="tickets",
        **ctx,
    )


@app.get("/tickets/<ticket_id>")
@login_required
def ticket_detail(ticket_id: str):
    ctx = _ctx()
    t = get_ticket(ticket_id)
    if not t or not _can_access_ticket(t, set(ctx["permissions"])):
        abort(404)
    t = {
        **t,
        "creator_display_name": _resolve_display_name(
            t.get("creator_user_id"), guild_id=t.get("guild_id") or DEFAULT_GUILD_ID
        ),
    }
    logs = list_logs_for_ticket(ticket_id, limit=200)
    messages = get_ticket_messages(ticket_id)
    close_reasons = list_close_reasons(DEFAULT_GUILD_ID)
    return render_template(
        "ticket_detail.html",
        t=t,
        logs=logs,
        messages=_format_date_fields(messages, "created_at"),
        close_reasons=close_reasons,
        active_page="tickets",
        **ctx,
    )


@app.get("/tickets/<ticket_id>/transcript")
@login_required
def ticket_transcript(ticket_id: str):
    t = get_ticket(ticket_id)
    if not t or not _can_access_ticket(t) or not t.get("transcript_path"):
        abort(404)
    path = _resolve_transcript_path(t["transcript_path"])
    if not path.exists():
        abort(404)
    html = _format_transcript_dates(path.read_text(encoding="utf-8"))
    ctx = _ctx()
    return render_template(
        "transcript.html",
        ticket_id=ticket_id,
        html=html,
        **ctx,
    )


@app.get("/t/<ticket_id>")
def public_transcript(ticket_id: str):
    token = request.args.get("token") or ""
    if not token:
        if current_user():
            return ticket_transcript(ticket_id)
        abort(403)
    data = verify_transcript_token(
        app.secret_key, token, max_age_seconds=60 * 60 * 24 * 7
    )
    if not data:
        abort(403)
    if str(data.get("ticket_id")) != str(ticket_id):
        abort(403)
    t = get_ticket(ticket_id)
    if not t:
        abort(404)
    transcript_path = t.get("transcript_path") or ""
    if not transcript_path:
        abort(404)
    path = _resolve_transcript_path(transcript_path)
    if not path.exists():
        abort(404)
    html = _format_transcript_dates(path.read_text(encoding="utf-8"))
    ctx = _ctx()
    return render_template(
        "transcript.html",
        ticket_id=ticket_id,
        html=html,
        **ctx,
    )


# -- Roles Management Page --


@app.get("/roles")
@permission_required("roles.manage")
def roles_page():
    ctx = _ctx()
    roles = list_roles(DEFAULT_GUILD_ID)
    server_roles = _live_discord_roles(DEFAULT_GUILD_ID)
    server_roles_by_id = {str(role["id"]): role for role in server_roles}
    total_members_with_web_role = 0
    for role in roles:
        count = count_role_members(
            DEFAULT_GUILD_ID, str(role.get("discord_role_id") or "")
        )
        role["member_count"] = count
        total_members_with_web_role += count
        live = server_roles_by_id.get(str(role.get("discord_role_id") or ""))
        role["discord_role"] = live
        role["color"] = (live or {}).get("color") or "#5865F2"
    total_permissions_assigned = sum(
        len(role.get("permissions") or []) for role in roles
    )
    selfrole_panels = get_all_selfrole_panels(DEFAULT_GUILD_ID)
    selfrole_meta: dict[str, dict] = {}
    selfrole_order: dict[str, tuple[int, int, str]] = {}
    for panel_index, panel in enumerate(selfrole_panels):
        mappings = panel.get("roles") or {}
        for mapping_index, (emoji, role_id) in enumerate(mappings.items()):
            normalized_role_id = str(role_id or "").strip()
            if not normalized_role_id:
                continue
            order = (panel_index, mapping_index, str(emoji))
            selfrole_order.setdefault(normalized_role_id, order)
            selfrole_meta.setdefault(
                normalized_role_id,
                {
                    "panel_title": panel.get("title") or "Selfrole-Panel",
                    "panel_id": panel.get("id"),
                    "message_id": panel.get("message_id"),
                    "emoji": str(emoji),
                    "order": order,
                },
            )
    selfrole_ids = set(selfrole_meta) or {
        str(role_id).strip() for role_id in get_selfrole_role_ids(DEFAULT_GUILD_ID)
    }
    for role in server_roles:
        role_id = str(role.get("id") or "").strip()
        role["is_selfrole"] = role_id in selfrole_ids
        role["selfrole_meta"] = selfrole_meta.get(role_id)
    regular_server_roles = [r for r in server_roles if not r.get("is_selfrole")]
    selfrole_server_roles = sorted(
        [r for r in server_roles if r.get("is_selfrole")],
        key=lambda r: selfrole_order.get(
            str(r.get("id") or "").strip(),
            (9999, 9999, str(r.get("name") or "").lower()),
        ),
    )
    return render_template(
        "roles.html",
        roles=roles,
        server_roles=server_roles,
        regular_server_roles=regular_server_roles,
        selfrole_server_roles=selfrole_server_roles,
        all_permissions=ALL_PERMISSIONS,
        permission_groups=PERMISSION_GROUPS,
        command_permission_groups=COMMAND_PERMISSION_GROUPS,
        permission_labels=PERMISSION_LABELS,
        total_members_with_web_role=total_members_with_web_role,
        total_permissions_assigned=total_permissions_assigned,
        active_page="roles",
        **ctx,
    )


@app.post("/roles/create")
@permission_required("roles.manage")
def roles_create():
    discord_role_id = (request.form.get("discord_role_id") or "").strip()
    role_name = (request.form.get("role_name") or "").strip()
    perms = [
        perm for perm in request.form.getlist("permissions") if perm in ALL_PERMISSIONS
    ]
    if not discord_role_id or not role_name:
        return redirect(url_for("roles_page"))
    guild, actor_member, bot_member = _live_role_context(DEFAULT_GUILD_ID)
    if guild:
        try:
            role = guild.get_role(int(discord_role_id))
        except ValueError:
            role = None
        if (
            role is None
            or not _role_dict(role, actor_member=actor_member, bot_member=bot_member)[
                "manageable"
            ]
        ):
            app.logger.warning(
                "Web role create blocked for unmanaged Discord role: %s",
                discord_role_id,
            )
            return redirect(url_for("roles_page"))
    create_role(DEFAULT_GUILD_ID, discord_role_id, role_name, perms)
    refresh_current_user_permissions()
    return redirect(url_for("roles_page"))


@app.post("/roles/<int:role_id>/update")
@permission_required("roles.manage")
def roles_update(role_id: int):
    role_name = (request.form.get("role_name") or "").strip()
    perms = [
        perm for perm in request.form.getlist("permissions") if perm in ALL_PERMISSIONS
    ]
    update_role(role_id, role_name=role_name or None, permissions=perms)
    refresh_current_user_permissions()
    return redirect(url_for("roles_page"))


@app.post("/roles/<int:role_id>/delete")
@permission_required("roles.manage")
def roles_delete(role_id: int):
    delete_role(role_id)
    refresh_current_user_permissions()
    return redirect(url_for("roles_page"))


@app.post("/roles/discord/create")
@permission_required("roles.manage")
def roles_discord_create():
    guild_id = DEFAULT_GUILD_ID
    role_name = (request.form.get("role_name") or "").strip()
    color_hex = (request.form.get("color") or "").strip() or None
    if role_name:
        role, error = _run_bot_coro(
            _discord_create_role(guild_id, role_name, color_hex)
        )
        if error:
            app.logger.warning("Discord role create failed: %s", error)
    return redirect(url_for("roles_page"))


@app.post("/roles/discord/assign")
@permission_required("roles.manage")
def roles_discord_assign():
    guild_id = DEFAULT_GUILD_ID
    user_id = (request.form.get("user_id") or "").strip()
    role_id = (request.form.get("role_id") or "").strip()
    actor_user_id = (current_user() or {}).get("discord_id")
    if user_id and role_id:
        roles, error = _run_bot_coro(
            _discord_add_member_role(guild_id, user_id, role_id, actor_user_id)
        )
        if roles is not None:
            update_guild_member_roles(guild_id, user_id, roles)
        elif error:
            app.logger.warning("Discord role assign failed: %s", error)
    return redirect(url_for("roles_page"))


@app.get("/panel-api/roles/<int:role_id>/members")
@permission_required("roles.manage")
def panel_api_role_members(role_id: int):
    role = get_role(role_id)
    if not role:
        return jsonify({"ok": False, "error": "not_found"}), 404
    guild_id = role.get("guild_id") or DEFAULT_GUILD_ID
    discord_role_id = str(role.get("discord_role_id") or "")
    members = list_role_members(guild_id, discord_role_id, limit=1000)
    items = []
    for m in members:
        items.append(
            {
                "user_id": m["user_id"],
                "display_name": m.get("display_name")
                or m.get("global_name")
                or m.get("username")
                or m["user_id"],
                "username": m.get("username") or "",
                "avatar_url": m.get("avatar_url") or "",
                "status": m.get("status") or "unknown",
                "presence_status": m.get("presence_status") or "",
                "joined_at": format_berlin_date(m.get("joined_at"))
                if m.get("joined_at")
                else "",
                "detail_url": url_for(
                    "user_detail_page", user_id=m["user_id"], guild_id=guild_id
                ),
            }
        )
    return jsonify(
        {
            "ok": True,
            "role": {
                "id": role["id"],
                "role_name": role["role_name"],
                "discord_role_id": discord_role_id,
                "permissions": role.get("permissions") or [],
            },
            "total": len(items),
            "members": items,
        }
    )


# -- Ticket Messages JSON (web session auth) --


@app.get("/tickets/<ticket_id>/messages.json")
@login_required
def ticket_messages_json(ticket_id: str):
    if not _can_access_ticket(get_ticket(ticket_id)):
        abort(404)
    messages = get_ticket_messages(ticket_id)
    return jsonify(_format_date_fields(messages, "created_at"))


# -- Ticket Reply from Web --


@app.post("/tickets/<ticket_id>/reply")
@login_required
def ticket_reply_web(ticket_id: str):
    if not has_permission("tickets.reply"):
        abort(403)
    if not _can_access_ticket(get_ticket(ticket_id)):
        abort(404)
    content = (request.form.get("content") or "").strip()
    if not content:
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    u = current_user()
    msg = add_ticket_message(
        ticket_id=ticket_id,
        author_id=u["discord_id"],
        author_name=u["username"],
        content=content,
        source="web",
    )

    # Send to Discord via bot if available
    bot = app.config.get("DISCORD_BOT")
    if bot and bot.is_ready():
        t = get_ticket(ticket_id)
        channel_id = t.get("channel_id") if t else None
        if channel_id:
            try:
                loop = bot.loop
                asyncio.run_coroutine_threadsafe(
                    _send_discord_reply(bot, int(channel_id), u["username"], content),
                    loop,
                )
            except Exception:
                pass

    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


async def _send_discord_reply(
    bot, channel_id: int, username: str, content: str
) -> None:
    channel = bot.get_channel(channel_id)
    if not channel:
        return
    await channel.send(content=f"**{username}** (Web Panel):\n{content}")


# -- Close Ticket from Web --


@app.post("/tickets/<ticket_id>/close")
@login_required
def ticket_close_web(ticket_id: str):
    if not has_permission("tickets.close"):
        abort(403)
    t = get_ticket(ticket_id)
    if not t or not _can_access_ticket(t) or t.get("status") == "closed":
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    reason = (request.form.get("reason") or "").strip() or "Über Web Panel geschlossen."
    u = current_user()

    # Mark closed in DB immediately so the page reflects the new state
    upsert_ticket(
        {
            "ticket_id": ticket_id,
            "status": "closed",
            "closed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "closed_by_id": u["discord_id"],
            "closed_by_name": u["username"],
            "close_reason": reason,
        }
    )

    # Let the bot's TicketSystemCog.close_ticket handle the rest
    # (transcript, logs, DM, archive, channel delete)
    bot = app.config.get("DISCORD_BOT")
    if bot and bot.is_ready():
        channel_id = t.get("channel_id")
        if channel_id:
            try:
                loop = bot.loop
                asyncio.run_coroutine_threadsafe(
                    _close_discord_ticket(
                        bot, int(channel_id), u["discord_id"], reason
                    ),
                    loop,
                )
            except Exception:
                pass

    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


async def _close_discord_ticket(
    bot, channel_id: int, closer_discord_id: str, reason: str
) -> None:
    channel = bot.get_channel(channel_id)
    if not channel:
        return

    guild = channel.guild
    # Try to get the web-panel user as a guild Member
    closer = guild.get_member(int(closer_discord_id))
    if not closer:
        try:
            closer = await guild.fetch_member(int(closer_discord_id))
        except Exception:
            closer = None

    cog = bot.get_cog("TicketSystemCog")
    if cog and closer:
        await cog.close_ticket(closer, channel, reason=reason)
    else:
        # Fallback if cog or member not available
        import discord as _discord

        embed = _discord.Embed(
            title="Ticket geschlossen",
            description=f"Dieses Ticket wurde über das Web Panel geschlossen.",
            color=_discord.Color.red(),
        )
        embed.add_field(name="Grund", value=reason, inline=False)
        try:
            await channel.send(embed=embed)
            await channel.delete(reason=f"Web Panel: {reason}")
        except Exception:
            pass


# -- Close Reasons Config Page --


@app.get("/close-reasons")
@permission_required("config.manage")
def close_reasons_page():
    ctx = _ctx()
    reasons = list_close_reasons(DEFAULT_GUILD_ID)
    return render_template(
        "close_reasons.html",
        reasons=reasons,
        active_page="close_reasons",
        **ctx,
    )


@app.post("/close-reasons/create")
@permission_required("config.manage")
def close_reasons_create():
    label = (request.form.get("label") or "").strip()
    if not label:
        return redirect(url_for("close_reasons_page"))
    sort_order = request.form.get("sort_order", "0")
    try:
        sort_order = int(sort_order)
    except ValueError:
        sort_order = 0
    add_close_reason(DEFAULT_GUILD_ID, label, sort_order)
    return redirect(url_for("close_reasons_page"))


@app.post("/close-reasons/<int:reason_id>/update")
@permission_required("config.manage")
def close_reasons_update(reason_id: int):
    label = (request.form.get("label") or "").strip()
    sort_order = request.form.get("sort_order")
    try:
        sort_order = int(sort_order) if sort_order else None
    except ValueError:
        sort_order = None
    update_close_reason(reason_id, label=label or None, sort_order=sort_order)
    return redirect(url_for("close_reasons_page"))


@app.post("/close-reasons/<int:reason_id>/delete")
@permission_required("config.manage")
def close_reasons_delete(reason_id: int):
    delete_close_reason(reason_id)
    return redirect(url_for("close_reasons_page"))


# -- Counting Overview Page --


@app.get("/counting")
@permission_any_required("counting.view", "counting.manage")
def counting_page():
    ctx = _ctx()
    state = get_counting(DEFAULT_GUILD_ID) or {}
    cache: dict[str, str] = {}
    state = {
        **state,
        "last_user_display_name": _resolve_display_name(
            state.get("last_user_id"), cache, guild_id=DEFAULT_GUILD_ID
        ),
    }
    return render_template(
        "counting.html",
        state=state,
        guild_id=DEFAULT_GUILD_ID,
        active_page="counting",
        **ctx,
    )


@app.post("/counting/set-channel")
@permission_required("counting.manage")
def counting_set_channel():
    channel_id = (request.form.get("channel_id") or "").strip()
    if channel_id:
        set_counting(DEFAULT_GUILD_ID, channel_id=channel_id)
    return redirect(url_for("counting_page"))


@app.post("/counting/reset")
@permission_required("counting.manage")
def counting_reset():
    set_counting(DEFAULT_GUILD_ID, last_number=0, last_user_id=None, highscore=0)
    return redirect(url_for("counting_page"))


@app.get("/users")
@permission_required("users.view")
def users_page():
    ctx = _ctx()
    guild_id = _active_panel_guild_id()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    if status not in {"all", "active", "left"}:
        status = "all"
    role_id = request.args.get("role_id", "").strip()
    presence = request.args.get("presence", "").strip().lower()
    if presence not in {"online", "idle", "dnd", "offline"}:
        presence = ""
    active_count = count_guild_members(guild_id, status="active")
    left_count = count_guild_members(guild_id, status="left")
    server_roles = _live_discord_roles(guild_id)
    return render_template(
        "users.html",
        q=q,
        guild_id=guild_id,
        status=status,
        role_id=role_id,
        presence=presence,
        server_roles=server_roles,
        active_count=active_count,
        left_count=left_count,
        active_page="users",
        **ctx,
    )


@app.get("/users/<user_id>")
@permission_required("users.view")
def user_detail_page(user_id: str):
    ctx = _ctx()
    guild_id = _active_panel_guild_id()
    member = get_guild_member(guild_id, user_id)
    if not member:
        member = {
            "guild_id": guild_id,
            "user_id": user_id,
            "username": user_id,
            "global_name": None,
            "display_name": user_id,
            "avatar_url": None,
            "banner_url": None,
            "accent_color": None,
            "locale": None,
            "is_bot": 0,
            "status": "unknown",
            "joined_at": None,
            "left_at": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "updated_at": None,
            "presence_status": None,
            "activity_name": None,
            "activity_type": None,
            "status_updated_at": None,
        }
    history = get_guild_member_name_history(guild_id, user_id)
    name_cache: dict[str, str | None] = {}
    for entry in history:
        if not entry.get("changed_by_name") and entry.get("changed_by_id"):
            entry["changed_by_name"] = _resolve_display_name(
                entry.get("changed_by_id"),
                name_cache,
                guild_id=guild_id,
            )
        if not entry.get("changed_by_name"):
            user_changed_identity = (
                (entry.get("old_username") or "") != (entry.get("new_username") or "")
                or (entry.get("old_global_name") or "")
                != (entry.get("new_global_name") or "")
            )
            if user_changed_identity:
                entry["changed_by_id"] = user_id
                entry["changed_by_name"] = (
                    member.get("display_name") or member.get("username") or user_id
                )
                entry["changed_by_note"] = "Aus alter Historie abgeleitet."
            else:
                entry["changed_by_note"] = (
                    "Bei alten Einträgen wurde der Auslöser noch nicht gespeichert."
                )
    oauth_user = get_user_by_discord_id(user_id) or {}
    if oauth_user:
        member["banner_url"] = member.get("banner_url") or oauth_user.get(
            "discord_banner"
        )
        if member.get("accent_color") is None:
            member["accent_color"] = oauth_user.get("accent_color")
        member["locale"] = member.get("locale") or oauth_user.get("locale")
    if (
        not member.get("banner_url")
        and member.get("accent_color") is None
        and not member.get("locale")
    ):
        profile, error = _run_bot_coro(_discord_fetch_user_profile(user_id))
        if profile:
            update_guild_member_profile_fields(guild_id, user_id, **profile)
            member["banner_url"] = member.get("banner_url") or profile.get("banner_url")
            if member.get("accent_color") is None:
                member["accent_color"] = profile.get("accent_color")
            member["locale"] = member.get("locale") or profile.get("locale")
        elif error and error != "Bot ist nicht verbunden.":
            app.logger.warning("Discord profile fetch failed: %s", error)
    member["accent_color"] = _accent_color_hex(member.get("accent_color"))
    member_roles = parse_member_roles(member)
    web_roles_by_discord_id = {
        str(role["discord_role_id"]): role for role in list_roles(guild_id)
    }
    member_web_roles = [
        web_roles_by_discord_id[str(role.get("id"))]
        for role in member_roles
        if str(role.get("id")) in web_roles_by_discord_id
    ]
    web_role_ids = set(web_roles_by_discord_id)
    discord_roles = _live_discord_roles(guild_id)
    discord_roles_by_id = {str(role["id"]): role for role in discord_roles}
    current_role_ids = {str(role.get("id")) for role in member_roles}
    message_stats = get_user_message_stats(guild_id, user_id)
    channel_stats = get_user_channel_message_stats(guild_id, user_id)
    ticket_stats = get_ticket_stats_for_user(guild_id, user_id)
    edited_message_count = count_guild_message_history(
        guild_id, user_id=user_id, event_type="edit"
    )
    deleted_message_count = count_guild_message_history(
        guild_id, user_id=user_id, event_type="delete"
    )
    birthday = get_birthday(get_birthdays_panel_guild_id(DEFAULT_GUILD_ID), user_id)
    return render_template(
        "user_detail.html",
        member=_format_date_fields(
            [member],
            "joined_at",
            "left_at",
            "first_seen_at",
            "last_seen_at",
            "updated_at",
            "status_updated_at",
        )[0],
        history=_format_date_fields(history, "changed_at"),
        member_roles=member_roles,
        member_web_roles=member_web_roles,
        discord_roles=discord_roles,
        discord_member_roles=[
            {
                **role,
                **discord_roles_by_id.get(str(role.get("id")), {}),
                "is_web_role": str(role.get("id")) in web_role_ids,
            }
            for role in member_roles
        ],
        assignable_discord_roles=[
            role
            for role in discord_roles
            if role["id"] not in current_role_ids and role.get("manageable")
        ],
        connections=list_user_connections(user_id),
        birthday=birthday,
        birthday_label=_birthday_label(birthday),
        message_stats=_format_date_fields([message_stats], "last_message_at")[0],
        channel_stats=_format_date_fields(channel_stats, "last_message_at"),
        ticket_stats=_format_date_fields([ticket_stats], "last_ticket_at")[0],
        edited_message_count=edited_message_count,
        deleted_message_count=deleted_message_count,
        guild_id=guild_id,
        active_page="users",
        **ctx,
    )


@app.post("/users/<user_id>/discord-roles/add")
@permission_required("roles.manage")
def user_discord_role_add(user_id: str):
    guild_id = _active_panel_guild_id()
    role_id = (request.form.get("role_id") or "").strip()
    actor_user_id = (current_user() or {}).get("discord_id")
    if role_id:
        roles, error = _run_bot_coro(
            _discord_add_member_role(guild_id, user_id, role_id, actor_user_id)
        )
        if roles is not None:
            update_guild_member_roles(guild_id, user_id, roles)
        elif error:
            app.logger.warning("Discord role add failed: %s", error)
    return redirect(url_for("user_detail_page", user_id=user_id, guild_id=guild_id))


@app.post("/users/<user_id>/discord-roles/<role_id>/remove")
@permission_required("roles.manage")
def user_discord_role_remove(user_id: str, role_id: str):
    guild_id = _active_panel_guild_id()
    actor_user_id = (current_user() or {}).get("discord_id")
    roles, error = _run_bot_coro(
        _discord_remove_member_role(guild_id, user_id, role_id, actor_user_id)
    )
    if roles is not None:
        update_guild_member_roles(guild_id, user_id, roles)
    elif error:
        app.logger.warning("Discord role remove failed: %s", error)
    return redirect(url_for("user_detail_page", user_id=user_id, guild_id=guild_id))


@app.post("/users/<user_id>/discord-roles/create")
@permission_required("roles.manage")
def user_discord_role_create(user_id: str):
    guild_id = _active_panel_guild_id()
    role_name = (request.form.get("role_name") or "").strip()
    color_hex = (request.form.get("color") or "").strip() or None
    if role_name:
        role, error = _run_bot_coro(
            _discord_create_role(guild_id, role_name, color_hex)
        )
        if error:
            app.logger.warning("Discord role create failed: %s", error)
        elif role and request.form.get("assign_created") == "1":
            actor_user_id = (current_user() or {}).get("discord_id")
            roles, assign_error = _run_bot_coro(
                _discord_add_member_role(guild_id, user_id, role["id"], actor_user_id)
            )
            if roles is not None:
                update_guild_member_roles(guild_id, user_id, roles)
            elif assign_error:
                app.logger.warning(
                    "Discord created role assign failed: %s", assign_error
                )
    return redirect(url_for("user_detail_page", user_id=user_id, guild_id=guild_id))


def _log_message_channel_ids(guild_id: str) -> set[str]:
    return {
        str(channel_id)
        for channel_id in get_all_log_channels(guild_id).values()
        if channel_id
    }


def _message_evaluated_stats(
    totals: dict,
    overview: dict,
    top_channels: list[dict],
    filter_users: list[dict],
    filter_channels: list[dict],
) -> list[dict]:
    return [
        {"label": "Nachrichten gesamt", "value": totals.get("message_count") or 0},
        {"label": "Schreibende User", "value": totals.get("active_writers") or 0},
        {"label": "Aktive Channels", "value": totals.get("active_channels") or 0},
        {"label": "Letzte Nachricht", "value": totals.get("last_message_at") or "-"},
        {
            "label": "Top-User ausgewertet",
            "value": len(overview.get("top_users") or []),
        },
        {"label": "Top-Channels ausgewertet", "value": len(top_channels)},
        {"label": "Nachrichtenfilter User", "value": len(filter_users)},
        {"label": "Nachrichtenfilter Channels", "value": len(filter_channels)},
    ]


@app.get("/stats")
@permission_any_required("stats.view", "stats.manage")
def stats_page():
    ctx = _ctx()
    guild_id = _active_panel_guild_id()
    q = request.args.get("q", "").strip()
    user_id = request.args.get("user_id", "").strip()
    channel_id = request.args.get("channel_id", "").strip()
    log_channel_ids = _log_message_channel_ids(guild_id)
    overview = get_guild_message_overview(
        guild_id, exclude_channel_ids=log_channel_ids
    )
    log_overview = get_guild_message_overview(
        guild_id, include_channel_ids=log_channel_ids
    )
    totals = _format_date_fields([overview.get("totals") or {}], "last_message_at")[0]
    top_channels = _format_date_fields(
        overview.get("top_channels") or [], "last_message_at"
    )
    log_top_channels = _format_date_fields(
        log_overview.get("top_channels") or [], "last_message_at"
    )
    log_totals = _format_date_fields(
        [log_overview.get("totals") or {}], "last_message_at"
    )[0]
    filter_users = _format_stats_filter_users(
        list_message_filter_users(guild_id, exclude_channel_ids=log_channel_ids)
    )
    filter_channels = list_message_filter_channels(
        guild_id, exclude_channel_ids=log_channel_ids
    )
    evaluated_stats = _message_evaluated_stats(
        totals, overview, top_channels, filter_users, filter_channels
    )
    return render_template(
        "stats.html",
        guild_id=guild_id,
        q=q,
        filter_user_id=user_id,
        filter_channel_id=channel_id,
        filter_users=filter_users,
        filter_channels=filter_channels,
        evaluated_stats=evaluated_stats,
        chart_data=get_guild_message_chart_data(
            guild_id, exclude_channel_ids=log_channel_ids
        ),
        log_stats={
            "totals": log_totals,
            "top_channels": log_top_channels,
            "configured_channels": len(log_channel_ids),
        },
        overview={
            **overview,
            "totals": totals,
            "top_channels": top_channels,
        },
        active_page="stats",
        **ctx,
    )


@app.get("/panel-api/stats/overview")
@permission_any_required("stats.view", "stats.manage")
def panel_api_stats_overview():
    guild_id = request.args.get("guild_id") or _active_panel_guild_id()
    log_channel_ids = _log_message_channel_ids(guild_id)
    overview = get_guild_message_overview(
        guild_id, exclude_channel_ids=log_channel_ids
    )
    log_overview = get_guild_message_overview(
        guild_id, include_channel_ids=log_channel_ids
    )
    totals = _format_date_fields([overview.get("totals") or {}], "last_message_at")[0]
    top_channels = _format_date_fields(
        overview.get("top_channels") or [], "last_message_at"
    )
    log_top_channels = _format_date_fields(
        log_overview.get("top_channels") or [], "last_message_at"
    )
    log_totals = _format_date_fields(
        [log_overview.get("totals") or {}], "last_message_at"
    )[0]
    filter_users = _format_stats_filter_users(
        list_message_filter_users(guild_id, exclude_channel_ids=log_channel_ids)
    )
    filter_channels = list_message_filter_channels(
        guild_id, exclude_channel_ids=log_channel_ids
    )
    evaluated_stats = _message_evaluated_stats(
        totals, overview, top_channels, filter_users, filter_channels
    )
    return jsonify(
        {
            "totals": totals,
            "evaluated_stats": evaluated_stats,
            "chart_data": get_guild_message_chart_data(
                guild_id, exclude_channel_ids=log_channel_ids
            ),
            "log_stats": {
                "totals": log_totals,
                "top_channels": log_top_channels,
                "configured_channels": len(log_channel_ids),
            },
        }
    )


# -- Birthdays Overview Page --


@app.get("/birthdays")
@permission_any_required("birthdays.view", "birthdays.manage")
def birthdays_page():
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    ctx = _ctx()
    legacy_message_id = get_config(birthdays_guild_id, "birthday_list_message_id")
    legacy_channel_id = get_config(birthdays_guild_id, "birthday_list_channel_id")
    if legacy_message_id:
        upsert_bot_message(
            birthdays_guild_id,
            "birthday_list",
            legacy_message_id,
            channel_id=legacy_channel_id,
            meta_key="birthdays",
        )
    birthday_channel = get_config(birthdays_guild_id, "birthday_channel_id")
    birthday_messages = list_bot_messages(birthdays_guild_id, "birthday_list")
    from datetime import datetime

    today = datetime.now()
    today_list = get_birthdays_today(birthdays_guild_id)
    cache: dict[str, str | None] = {}
    today_list = [
        {
            **b,
            "display_name": _resolve_display_name(
                b.get("user_id"), cache, guild_id=birthdays_guild_id
            ),
        }
        for b in today_list
    ]
    upcoming = get_upcoming_birthdays(birthdays_guild_id, days=30, limit=8)
    upcoming = [
        {
            **u,
            "display_name": _resolve_display_name(
                u.get("user_id"), cache, guild_id=birthdays_guild_id
            ),
        }
        for u in upcoming
    ]
    return render_template(
        "birthdays.html",
        birthday_count=count_birthdays(birthdays_guild_id),
        birthday_channel=birthday_channel,
        birthday_messages=birthday_messages,
        birthdays_guild_id=birthdays_guild_id,
        today_count=len(today_list),
        today_list=today_list,
        month_count=count_birthdays_in_month(birthdays_guild_id, today.month),
        upcoming=upcoming,
        active_page="birthdays",
        **ctx,
    )


def _trigger_birthday_list_refresh(guild_id: str) -> None:
    bot = app.config.get("DISCORD_BOT")
    if not bot or not bot.is_ready():
        return
    try:
        guild = bot.get_guild(int(guild_id))
        if guild is None:
            return
        cog = bot.get_cog("BirthdayCog")
        if cog is None:
            return
        asyncio.run_coroutine_threadsafe(
            cog._update_birthday_list_message(guild), bot.loop
        )
    except Exception:
        pass


@app.post("/birthdays/set-channel")
@permission_required("birthdays.manage")
def birthdays_set_channel():
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    channel_id = (request.form.get("channel_id") or "").strip()
    if channel_id:
        set_config(birthdays_guild_id, "birthday_channel_id", channel_id)
    else:
        delete_config(birthdays_guild_id, "birthday_channel_id")
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/<user_id>/set")
@permission_required("birthdays.manage")
def birthdays_set(user_id: str):
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    day = request.form.get("day", type=int)
    month = request.form.get("month", type=int)
    year = request.form.get("year", type=int) or None
    if day and month:
        set_birthday(birthdays_guild_id, user_id, day, month, year)
        _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/add")
@permission_required("birthdays.manage")
def birthdays_add():
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    user_id = (request.form.get("user_id") or "").strip()
    day = request.form.get("day", type=int)
    month = request.form.get("month", type=int)
    year = request.form.get("year", type=int) or None
    if user_id and day and month:
        set_birthday(birthdays_guild_id, user_id, day, month, year)
        _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/<user_id>/delete")
@permission_required("birthdays.manage")
def birthdays_delete(user_id: str):
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    delete_birthday(birthdays_guild_id, user_id)
    _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/messages/add")
@permission_required("birthdays.manage")
def birthdays_add_message():
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    message_id = (request.form.get("message_id") or "").strip()
    channel_id = (request.form.get("channel_id") or "").strip() or None
    if message_id:
        upsert_bot_message(
            birthdays_guild_id,
            "birthday_list",
            message_id,
            channel_id=channel_id,
            meta_key="birthdays",
        )
        _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/messages/<message_id>/delete")
@permission_required("birthdays.manage")
def birthdays_delete_message(message_id: str):
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    delete_bot_message(birthdays_guild_id, "birthday_list", message_id)
    _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


# -- Warnings Overview Page --


@app.get("/warnings")
@permission_any_required("warnings.view", "warnings.manage", "users.warn")
def warnings_page():
    ctx = _ctx()
    q_user = request.args.get("user_id", "").strip()
    cache: dict[str, str | None] = {}
    return render_template(
        "warnings.html",
        warning_count=count_warnings(DEFAULT_GUILD_ID, q_user or None),
        q_user=q_user,
        q_user_display_name=_resolve_display_name(
            q_user, cache, guild_id=DEFAULT_GUILD_ID
        )
        if q_user
        else None,
        guild_id=DEFAULT_GUILD_ID,
        active_page="warnings",
        **ctx,
    )


@app.post("/warnings/<int:warning_id>/delete")
@permission_any_required("warnings.manage", "users.warn")
def warnings_delete(warning_id: int):
    remove_warning(warning_id)
    return redirect(url_for("warnings_page"))


# -- Change Updates Pages --


def _render_change_updates(kind: str):
    config = CHANGE_UPDATE_TYPES[kind]
    if not (
        has_permission(config["view_permission"])
        or has_permission(config["send_permission"])
    ):
        abort(403)
    ctx = _ctx()
    show_git = kind == "bot"
    summary_limit = request.args.get("summary_limit", 10, type=int) or 10
    summary_limit = max(1, min(50, summary_limit))
    commits = _git_commit_summary(summary_limit) if show_git else []
    selected_hashes = request.args.getlist("commit_hashes")
    selected_commits = _selected_git_commits(commits, selected_hashes)
    if show_git and not selected_commits:
        selected_commits = commits[: min(5, len(commits))]
    latest_commits = _git_commit_summary(5) if show_git else []
    channel_id = get_log_channel(DEFAULT_GUILD_ID, config["log_type"])
    channel_names = get_channel_names(
        DEFAULT_GUILD_ID, [channel_id] if channel_id else []
    )
    recent_updates = []
    for entry in list_discord_log_entries(
        DEFAULT_GUILD_ID,
        log_type=config["log_type"],
        limit=10,
    ):
        item = dict(entry)
        parsed_title, parsed_summary = _split_log_content(item.get("content"))
        item["event_title"] = item.get("event_title") or parsed_title or config["singular"]
        item["event_summary"] = (
            item.get("event_summary") or parsed_summary or item.get("content") or ""
        )
        item["actor_label"] = (
            item.get("actor_name")
            or _extract_change_actor(item.get("content"))
            or item.get("author_name")
            or "Unbekannt"
        )
        recent_updates.append(item)
    return render_template(
        "team_changes.html",
        change_kind=kind,
        change_config=config,
        active_page=config["active_page"],
        log_channel_id=channel_id,
        log_channel_name=channel_names.get(str(channel_id)) if channel_id else None,
        latest_commits=latest_commits,
        commits=commits,
        selected_hashes=[commit["hash"] for commit in selected_commits],
        selected_commits=selected_commits,
        selected_summary=_format_git_summary(selected_commits),
        summary_limit=summary_limit,
        show_git=show_git,
        recent_updates=_format_date_fields(
            recent_updates, "created_at", "edited_at", "synced_at"
        ),
        ping_roles=_team_ping_role_options(DEFAULT_GUILD_ID),
        error=request.args.get("error"),
        success=request.args.get("success"),
        **ctx,
    )


@app.get("/team-changes")
@login_required
def team_changes_page():
    return _render_change_updates("team")


@app.get("/bot-changes")
@login_required
def bot_changes_page():
    return _render_change_updates("bot")


def _handle_change_send(kind: str):
    config = CHANGE_UPDATE_TYPES[kind]
    if not has_permission(config["send_permission"]):
        abort(403)
    content = (request.form.get("message") or "").strip()
    show_git = kind == "bot"
    include_git = show_git and request.form.get("include_git") == "1"
    summary_limit = request.form.get("summary_limit", 10, type=int) or 10
    summary_limit = max(1, min(50, summary_limit))
    commits = _git_commit_summary(summary_limit) if show_git else []
    selected_commits = _selected_git_commits(
        commits,
        request.form.getlist("commit_hashes"),
    )
    ping_role_ids = _valid_ping_role_ids(
        DEFAULT_GUILD_ID,
        request.form.getlist("ping_role_ids")
        + ([request.form.get("ping_role_id")] if request.form.get("ping_role_id") else []),
    )
    if not content and not (show_git and include_git and selected_commits):
        return redirect(
            url_for(
                config["endpoint"],
                summary_limit=summary_limit,
                error="Nachricht oder ausgewählte Git-Einträge erforderlich."
                if show_git
                else "Nachricht darf nicht leer sein.",
            )
        )

    channel_id = get_log_channel(DEFAULT_GUILD_ID, config["log_type"])
    if not channel_id:
        return redirect(
            url_for(
                config["endpoint"],
                summary_limit=summary_limit,
                error=f"Kein Channel für {config['title']} unter Log Channels definiert.",
            )
        )

    user = current_user() or {}
    author = user.get("username") or "Web Panel"
    git_summary = _format_git_summary(selected_commits) if include_git else None
    try:
        target_channel_id = int(channel_id)
    except (TypeError, ValueError):
        return redirect(
            url_for(
                config["endpoint"],
                summary_limit=summary_limit,
                error=f"Der Channel für {config['title']} ist keine gültige Discord-ID.",
            )
        )
    sent_message, error = _run_bot_coro(
        _send_change_message(
            target_channel_id,
            config["singular"],
            author,
            content,
            git_summary,
            ping_role_ids,
        )
    )
    if error:
        return redirect(
            url_for(
                config["endpoint"],
                summary_limit=summary_limit,
                error=f"Senden fehlgeschlagen: {error}",
            )
        )
    if sent_message is not None:
        try:
            bot = app.config.get("DISCORD_BOT")
            if bot and hasattr(bot, "log_message_payload"):
                payload = bot.log_message_payload(sent_message)
            else:
                payload = {
                    "channel_id": str(channel_id),
                    "channel_name": None,
                    "message_id": str(getattr(sent_message, "id", "")),
                    "author_id": str(getattr(getattr(sent_message, "author", None), "id", "") or ""),
                    "author_name": str(getattr(sent_message, "author", "") or ""),
                    "content": str(getattr(sent_message, "content", "") or ""),
                    "jump_url": getattr(sent_message, "jump_url", None),
                    "created_at": getattr(sent_message, "created_at", None),
                    "edited_at": getattr(sent_message, "edited_at", None),
                }
            payload.update(
                {
                    "actor_id": str(user.get("discord_id") or "") or None,
                    "actor_name": author,
                    "event_title": config["singular"],
                    "event_summary": content[:1200] if content else git_summary,
                }
            )
            upsert_discord_log_entry(DEFAULT_GUILD_ID, config["log_type"], payload)
        except Exception:
            app.logger.exception("Change update log could not be saved")
    return redirect(
        url_for(
            config["endpoint"],
            summary_limit=summary_limit,
            success=f"{config['singular']} wurde gesendet.",
        )
    )


@app.post("/team-changes/send")
@permission_required("team_updates.send")
def team_changes_send():
    return _handle_change_send("team")


@app.post("/bot-changes/send")
@permission_required("bot_updates.send")
def bot_changes_send():
    return _handle_change_send("bot")


# -- Log Channels Config Page --


@app.get("/log-channels")
@permission_required("config.manage")
def log_channels_page():
    ctx = _ctx()
    raw = get_all_log_channels(DEFAULT_GUILD_ID)
    log_types = LOG_TYPES
    names = get_channel_names(DEFAULT_GUILD_ID, list(raw.values()))
    channels: dict[str, dict] = {}
    for lt in log_types:
        cid = raw.get(lt)
        if cid:
            channels[lt] = {
                "channel_id": str(cid),
                "channel_name": names.get(str(cid)),
            }
    return render_template(
        "log_channels.html",
        channels=channels,
        log_types=log_types,
        active_page="log_channels",
        **ctx,
    )


@app.get("/discord-logs")
@permission_required("logs.view")
def discord_logs_page():
    ctx = _ctx()
    guild_id = _active_panel_guild_id()
    _trigger_discord_log_sync(guild_id)
    channels = get_all_log_channels(guild_id)
    log_type_labels = {
        "voice_log": "Voice-Log",
        "user_log": "User",
        "server_log": "Server",
        "message_log": "Nachrichten",
        "welcome_log": "Welcome",
        "team_change_log": "Team",
        "bot_change_log": "Bot",
    }
    seen_log_types: set[str] = set()
    log_type_options = []
    for log_type in LOG_TYPES:
        if log_type not in channels or log_type in seen_log_types:
            continue
        seen_log_types.add(log_type)
        log_type_options.append(
            {"value": log_type, "label": log_type_labels.get(log_type, log_type)}
        )
    overview = get_discord_log_overview(guild_id)
    return render_template(
        "discord_logs.html",
        guild_id=guild_id,
        channels=channels,
        log_type_options=log_type_options,
        overview=_format_date_fields(
            [overview], "latest_created_at", "latest_synced_at"
        )[0],
        active_page="discord_logs",
        **ctx,
    )


@app.post("/log-channels/set")
@permission_required("config.manage")
def log_channels_set():
    log_type = (request.form.get("log_type") or "").strip()
    channel_id = (request.form.get("channel_id") or "").strip()
    if log_type in LOG_TYPES and channel_id:
        set_log_channel(DEFAULT_GUILD_ID, log_type, channel_id)
    return redirect(url_for("log_channels_page"))


@app.post("/log-channels/<log_type>/delete")
@permission_required("config.manage")
def log_channels_delete(log_type: str):
    if log_type in LOG_TYPES:
        remove_log_channel(DEFAULT_GUILD_ID, log_type)
    return redirect(url_for("log_channels_page"))


# -- Auto Publisher Config Page --


@app.get("/auto-publisher")
@permission_required("config.manage")
def auto_publisher_page():
    ctx = _ctx()
    raw = get_auto_publisher_channels(DEFAULT_GUILD_ID)
    names = get_channel_names(DEFAULT_GUILD_ID, raw)
    channels = [
        {"channel_id": str(cid), "channel_name": names.get(str(cid))} for cid in raw
    ]
    return render_template(
        "auto_publisher.html",
        channels=channels,
        active_page="auto_publisher",
        **ctx,
    )


@app.post("/auto-publisher/add")
@permission_required("config.manage")
def auto_publisher_add():
    channel_id = (request.form.get("channel_id") or "").strip()
    if channel_id:
        add_auto_publisher_channel(DEFAULT_GUILD_ID, channel_id)
    return redirect(url_for("auto_publisher_page"))


@app.post("/auto-publisher/<channel_id>/delete")
@permission_required("config.manage")
def auto_publisher_delete(channel_id: str):
    remove_auto_publisher_channel(DEFAULT_GUILD_ID, channel_id)
    return redirect(url_for("auto_publisher_page"))


# -- Server Stats Config Page --


@app.get("/server-stats")
@permission_required("config.manage")
def server_stats_page():
    ctx = _ctx()
    stats = get_server_stats(DEFAULT_GUILD_ID)
    stat_types = ["all", "members", "bots", "channels", "log_channels", "roles"]
    ids = [stats.get(k) for k in stat_types if stats.get(k)]
    if stats.get("category_id"):
        ids.append(stats["category_id"])
    channel_names = get_channel_names(DEFAULT_GUILD_ID, ids)
    return render_template(
        "server_stats.html",
        stats=stats,
        stat_types=stat_types,
        channel_names=channel_names,
        active_page="server_stats",
        **ctx,
    )


@app.post("/server-stats/save")
@permission_required("config.manage")
def server_stats_save():
    category_id = (request.form.get("category_id") or "").strip() or None
    stats = {}
    for key in ["all", "members", "bots", "channels", "log_channels", "roles"]:
        channel_id = (request.form.get(f"stat_{key}") or "").strip()
        if channel_id:
            stats[key] = channel_id
    set_server_stats(DEFAULT_GUILD_ID, category_id, stats)

    # Trigger bot to update voice channel names immediately
    bot = app.config.get("DISCORD_BOT")
    if bot and bot.is_ready():
        try:
            guild = bot.get_guild(int(DEFAULT_GUILD_ID))
            if guild:
                cog = bot.get_cog("ServerStatsCog")
                if cog:
                    asyncio.run_coroutine_threadsafe(
                        cog._update_guild_stats(guild), bot.loop
                    )
        except Exception:
            pass

    return redirect(url_for("server_stats_page"))


@app.get("/panel-api/tickets")
@login_required
def panel_api_tickets():
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "all")
    status_arg = status_filter if status_filter in {"open", "closed"} else None
    page, page_size, offset = _pagination_args()
    categories = _allowed_ticket_categories(
        set((current_user() or {}).get("permissions", set()))
    )
    rows = []
    for ticket in list_tickets(
        q=q, limit=page_size, offset=offset, categories=categories, status=status_arg
    ):
        guild_id = ticket.get("guild_id") or DEFAULT_GUILD_ID
        item = _attach_member_profile(ticket, guild_id, "creator_user_id", "creator")
        item["detail_url"] = url_for("ticket_detail", ticket_id=item["ticket_id"])
        rows.append(item)
    return _paginated_response(
        rows,
        count_tickets(q=q, categories=categories, status=status_arg),
        page,
        page_size,
    )


@app.get("/panel-api/users/<user_id>/tickets")
@login_required
def panel_api_user_tickets(user_id: str):
    guild_id = _active_panel_guild_id()
    page, page_size, offset = _pagination_args()
    categories = _allowed_ticket_categories(
        set((current_user() or {}).get("permissions", set()))
    )
    rows = []
    for ticket in list_tickets_for_user(
        guild_id, user_id, limit=page_size, offset=offset, categories=categories
    ):
        item = dict(ticket)
        item["detail_url"] = url_for("ticket_detail", ticket_id=item["ticket_id"])
        rows.append(item)
    return _paginated_response(
        rows,
        count_tickets_for_user(guild_id, user_id, categories=categories),
        page,
        page_size,
    )


@app.get("/panel-api/users")
@permission_required("users.view")
def panel_api_users():
    guild_id = _active_panel_guild_id()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    if status not in {"all", "active", "left"}:
        status = "all"
    role_id = request.args.get("role_id", "").strip() or None
    presence = request.args.get("presence", "").strip().lower() or None
    if presence not in {"online", "idle", "dnd", "offline", None}:
        presence = None
    page, page_size, offset = _pagination_args()
    rows = list_guild_members(
        guild_id,
        q=q,
        status=status,
        limit=page_size,
        offset=offset,
        role_id=role_id,
        presence=presence,
    )
    web_roles_by_discord_id = {
        str(role["discord_role_id"]): role["role_name"] for role in list_roles(guild_id)
    }
    for row in rows:
        row["detail_url"] = url_for(
            "user_detail_page", user_id=row["user_id"], guild_id=guild_id
        )
        try:
            roles = json.loads(row.get("roles_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            roles = []
        role_names = [
            str(role.get("name") or role.get("id"))
            for role in roles
            if isinstance(role, dict) and (role.get("name") or role.get("id"))
        ]
        web_role_names = [
            web_roles_by_discord_id[str(role.get("id"))]
            for role in roles
            if isinstance(role, dict) and str(role.get("id")) in web_roles_by_discord_id
        ]
        row["web_roles_label"] = (
            ", ".join(web_role_names[:3]) if web_role_names else "-"
        )
        if len(web_role_names) > 3:
            row["web_roles_label"] += f" +{len(web_role_names) - 3}"
        row["discord_roles_label"] = ", ".join(role_names[:4]) if role_names else "-"
        if len(role_names) > 4:
            row["discord_roles_label"] += f" +{len(role_names) - 4}"
        row["roles_label"] = row["discord_roles_label"]

        # ── Richer badge data for new UI ──
        def _hex(c):
            try:
                n = int(c or 0)
                if n <= 0:
                    return None
                return "#{:06x}".format(n & 0xFFFFFF)
            except (TypeError, ValueError):
                return None

        row["discord_roles_badges"] = [
            {"label": str(r.get("name") or r.get("id")), "color": _hex(r.get("color"))}
            for r in roles
            if isinstance(r, dict) and (r.get("name") or r.get("id"))
        ][:6]
        row["web_roles_badges"] = [
            {"label": web_roles_by_discord_id[str(r.get("id"))], "color": "#22d3ee"}
            for r in roles
            if isinstance(r, dict) and str(r.get("id")) in web_roles_by_discord_id
        ]
        row["presence_label"] = {
            "online": "Online",
            "idle": "Idle",
            "dnd": "DND",
            "offline": "Offline",
        }.get((row.get("presence_status") or "").lower(), "—")
    return _paginated_response(
        _format_date_fields(
            rows,
            "joined_at",
            "left_at",
            "first_seen_at",
            "last_seen_at",
            "updated_at",
            "last_message_at",
            "status_updated_at",
        ),
        count_guild_members(
            guild_id, q=q, status=status, role_id=role_id, presence=presence
        ),
        page,
        page_size,
    )


@app.get("/panel-api/users/suggest")
@permission_required("users.view")
def panel_api_users_suggest():
    guild_id = _active_panel_guild_id()
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    rows = list_guild_members(guild_id, q=q, status="all", limit=8, offset=0)
    suggestions = []
    for row in rows:
        suggestions.append(
            {
                "user_id": row.get("user_id"),
                "display_name": row.get("display_name")
                or row.get("global_name")
                or row.get("username"),
                "username": row.get("username"),
                "avatar_url": row.get("avatar_url"),
                "status": row.get("status"),
            }
        )
    return jsonify(suggestions)


@app.get("/panel-api/messages")
@permission_required("users.view")
def panel_api_messages():
    guild_id = request.args.get("guild_id") or _active_panel_guild_id()
    user_id = request.args.get("user_id", "").strip() or None
    channel_id = request.args.get("channel_id", "").strip() or None
    q = request.args.get("q", "").strip()
    include_deleted = request.args.get("include_deleted", "1") != "0"
    include_changed = request.args.get("include_changed", "1") != "0"
    exclude_channel_ids = None if channel_id else _log_message_channel_ids(guild_id)
    page, page_size, offset = _pagination_args()
    rows = []
    for message in list_guild_messages(
        guild_id,
        user_id=user_id,
        channel_id=channel_id,
        q=q,
        include_deleted=include_deleted,
        include_changed=include_changed,
        exclude_channel_ids=exclude_channel_ids,
        limit=page_size,
        offset=offset,
    ):
        item = dict(message)
        item["attachment_urls"] = _json_list(item.get("attachment_urls_json"))
        is_deleted = bool(item.get("deleted_at"))
        is_edited = bool(item.get("edited_at")) and (
            (item.get("original_content") or "") != (item.get("content") or "")
        )
        if is_deleted:
            item["message_status"] = "Gelöscht"
            item["_row_class"] = "bg-red-500/10 hover:bg-red-500/15"
        elif is_edited:
            item["message_status"] = "Bearbeitet"
            item["_row_class"] = "bg-amber-500/10 hover:bg-amber-500/15"
        else:
            item["message_status"] = "Original"
            item["_row_class"] = ""
        item["message_status_variant"] = (
            "danger" if is_deleted else "warning" if is_edited else "default"
        )
        item["user_detail_url"] = url_for(
            "user_detail_page", user_id=item["user_id"], guild_id=guild_id
        )
        rows.append(item)
    return _paginated_response(
        _format_date_fields(rows, "created_at", "edited_at", "deleted_at", "synced_at"),
        count_guild_messages(
            guild_id,
            user_id=user_id,
            channel_id=channel_id,
            q=q,
            include_deleted=include_deleted,
            include_changed=include_changed,
            exclude_channel_ids=exclude_channel_ids,
        ),
        page,
        page_size,
    )


@app.get("/panel-api/message-history")
@permission_required("users.view")
def panel_api_message_history():
    guild_id = request.args.get("guild_id") or _active_panel_guild_id()
    user_id = request.args.get("user_id", "").strip() or None
    event_type = request.args.get("event_type", "").strip() or None
    if event_type not in {"edit", "delete", None}:
        event_type = None
    page, page_size, offset = _pagination_args()
    rows = []
    for event in list_guild_message_history(
        guild_id,
        user_id=user_id,
        event_type=event_type,
        limit=page_size,
        offset=offset,
    ):
        item = dict(event)
        item["attachment_urls"] = _json_list(item.get("attachment_urls_json"))
        item["event_label"] = (
            "Bearbeitet" if item.get("event_type") == "edit" else "Gelöscht"
        )
        item["message_status"] = item["event_label"]
        item["user_detail_url"] = (
            url_for("user_detail_page", user_id=item["user_id"], guild_id=guild_id)
            if item.get("user_id")
            else None
        )
        rows.append(item)
    return _paginated_response(
        _format_date_fields(rows, "event_at", "synced_at"),
        count_guild_message_history(guild_id, user_id=user_id, event_type=event_type),
        page,
        page_size,
    )


@app.get("/panel-api/discord-logs")
@permission_required("logs.view")
def panel_api_discord_logs():
    guild_id = request.args.get("guild_id") or _active_panel_guild_id()
    log_type = request.args.get("log_type", "").strip() or None
    channel_id = request.args.get("channel_id", "").strip() or None
    q = request.args.get("q", "").strip()
    page, page_size, offset = _pagination_args(default_page_size=25)
    log_type_labels = {
        "voice_log": "Voice-Log",
        "user_log": "User",
        "server_log": "Server",
        "message_log": "Nachrichten",
        "welcome_log": "Welcome",
        "team_change_log": "Team",
        "bot_change_log": "Bot",
    }
    rows = []
    for entry in list_discord_log_entries(
        guild_id,
        log_type=log_type,
        channel_id=channel_id,
        q=q,
        limit=page_size,
        offset=offset,
    ):
        item = dict(entry)
        item["log_type_label"] = log_type_labels.get(
            item.get("log_type"), item.get("log_type") or "-"
        )
        parsed_title, parsed_summary = _split_log_content(item.get("content"))
        item["event_title"] = item.get("event_title") or parsed_title or "-"
        item["event_summary"] = (
            item.get("event_summary") or parsed_summary or item.get("content") or "-"
        )
        change_actor = _extract_change_actor(item.get("content"))
        item["actor_label"] = (
            item.get("actor_name")
            or change_actor
            or item.get("author_name")
            or item.get("author_id")
            or "-"
        )
        item["bot_author_label"] = item.get("author_name") or item.get("author_id") or "-"
        item["message_url"] = item.get("jump_url")
        meta = []
        if item.get("embed_count"):
            meta.append(f"{item['embed_count']} Embed(s)")
        if item.get("attachment_count"):
            meta.append(f"{item['attachment_count']} Anhang/Anhänge")
        item["log_meta"] = " · ".join(meta) if meta else "-"
        rows.append(item)
    return _paginated_response(
        _format_date_fields(rows, "created_at", "edited_at", "synced_at"),
        count_discord_log_entries(
            guild_id, log_type=log_type, channel_id=channel_id, q=q
        ),
        page,
        page_size,
    )


@app.get("/panel-api/discord-logs/overview")
@permission_required("logs.view")
def panel_api_discord_logs_overview():
    guild_id = request.args.get("guild_id") or _active_panel_guild_id()
    overview = get_discord_log_overview(guild_id)
    overview = _format_date_fields([overview], "latest_created_at", "latest_synced_at")[
        0
    ]
    overview["channel_count"] = len(get_all_log_channels(guild_id))
    return jsonify(overview)


@app.get("/panel-api/birthdays")
@permission_any_required("birthdays.view", "birthdays.manage")
def panel_api_birthdays():
    guild_id = request.args.get("guild_id") or get_birthdays_panel_guild_id(
        DEFAULT_GUILD_ID
    )
    page, page_size, offset = _pagination_args()
    month_names = {
        1: "Januar",
        2: "Februar",
        3: "März",
        4: "April",
        5: "Mai",
        6: "Juni",
        7: "Juli",
        8: "August",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "Dezember",
    }
    rows = []
    for row in get_birthdays(guild_id, limit=page_size, offset=offset):
        item = _attach_member_profile(row, guild_id, "user_id", "user")
        try:
            day = int(item.get("day") or 0)
            month = int(item.get("month") or 0)
        except (TypeError, ValueError):
            day = 0
            month = 0
        item["date_label"] = (
            f"{day:02d}.{month:02d}" if day and month else "Ungültiges Datum"
        ) + (f".{item['year']}" if item.get("year") and day and month else "")
        item["month_name"] = month_names.get(month, "?")
        item["delete_url"] = url_for("birthdays_delete", user_id=item["user_id"])
        rows.append(item)
    return _paginated_response(rows, count_birthdays(guild_id), page, page_size)


@app.get("/panel-api/warnings")
@permission_any_required("warnings.view", "warnings.manage", "users.warn")
def panel_api_warnings():
    guild_id = request.args.get("guild_id") or DEFAULT_GUILD_ID
    q_user = request.args.get("user_id", "").strip()
    q_mod = request.args.get("moderator_id", "").strip()
    q_reason = request.args.get("reason", "").strip()
    q_from = request.args.get("date_from", "").strip() or None
    q_to = request.args.get("date_to", "").strip() or None
    page, page_size, offset = _pagination_args()
    filters = dict(
        moderator_id=q_mod or None,
        reason_query=q_reason or None,
        date_from=q_from,
        date_to=q_to,
    )
    warnings = list_all_warnings(
        guild_id,
        limit=page_size,
        offset=offset,
        user_id=q_user or None,
        **filters,
    )
    rows = []
    for warning in warnings:
        item = _attach_member_profile(warning, guild_id, "user_id", "user")
        item = _attach_member_profile(item, guild_id, "moderator_id", "moderator")
        item["delete_url"] = url_for("warnings_delete", warning_id=item["id"])
        rows.append(item)
    return _paginated_response(
        rows,
        count_warnings(guild_id, q_user or None, **filters),
        page,
        page_size,
    )


@app.get("/panel-api/counting/leaderboard")
@permission_any_required("counting.view", "counting.manage")
def panel_api_counting_leaderboard():
    guild_id = request.args.get("guild_id") or DEFAULT_GUILD_ID
    page, page_size, offset = _pagination_args()
    rows = []
    for index, entry in enumerate(
        get_counting_leaderboard(guild_id, limit=page_size, offset=offset),
        start=offset + 1,
    ):
        item = _attach_member_profile(entry, guild_id, "user_id", "user")
        item["rank"] = index
        rows.append(item)
    return _paginated_response(
        rows, count_counting_leaderboard(guild_id), page, page_size
    )


# --------------------------------------------------------
#  API ENDPOINTS (called by the bot via ApiClient)
# --------------------------------------------------------

# -- Guild Config --


@app.get("/api/guild/<guild_id>/config/<key>")
@api_key_required
def api_get_config(guild_id: str, key: str):
    val = get_config(guild_id, key)
    if val is None:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "value": val})


@app.route("/api/guild/<guild_id>/config/<key>", methods=["PUT"])
@api_key_required
def api_set_config(guild_id: str, key: str):
    data = request.get_json(silent=True) or {}
    set_config(guild_id, key, str(data.get("value", "")))
    return jsonify({"ok": True})


# -- Birthdays --


@app.get("/api/guild/<guild_id>/birthdays")
@api_key_required
def api_get_birthdays(guild_id: str):
    return jsonify(get_birthdays(guild_id))


@app.get("/api/guild/<guild_id>/members")
@api_key_required
def api_get_guild_members(guild_id: str):
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    limit = request.args.get("limit", 500, type=int)
    limit = max(1, min(2000, limit or 500))
    return jsonify(list_guild_members(guild_id, q=q, status=status, limit=limit))


@app.post("/api/guild/<guild_id>/members/sync")
@api_key_required
def api_sync_guild_members(guild_id: str):
    data = request.get_json(silent=True) or {}
    members = data.get("members") or []
    if not isinstance(members, list):
        return jsonify({"ok": False, "error": "members_must_be_list"}), 400
    result = sync_guild_members(
        guild_id,
        members,
        mark_missing_left=bool(data.get("mark_missing_left", True)),
    )
    return jsonify({"ok": True, **result})


@app.get("/api/guild/<guild_id>/members/<user_id>")
@api_key_required
def api_get_guild_member(guild_id: str, user_id: str):
    member = get_guild_member(guild_id, user_id)
    if not member:
        return jsonify({"ok": False}), 404
    return jsonify(member)


@app.put("/api/guild/<guild_id>/members/<user_id>")
@api_key_required
def api_upsert_guild_member(guild_id: str, user_id: str):
    data = request.get_json(silent=True) or {}
    row = upsert_guild_member(guild_id, {**data, "user_id": user_id})
    return jsonify(row)


@app.post("/api/guild/<guild_id>/members/<user_id>/left")
@api_key_required
def api_mark_guild_member_left(guild_id: str, user_id: str):
    mark_guild_member_left(guild_id, user_id)
    return jsonify({"ok": True})


@app.get("/api/guild/<guild_id>/members/<user_id>/name-history")
@api_key_required
def api_get_guild_member_name_history(guild_id: str, user_id: str):
    return jsonify(get_guild_member_name_history(guild_id, user_id))


@app.post("/api/guild/<guild_id>/messages")
@api_key_required
def api_upsert_guild_message(guild_id: str):
    data = request.get_json(silent=True) or {}
    row = upsert_guild_message(guild_id, data)
    return jsonify(row)


@app.post("/api/guild/<guild_id>/messages/bulk")
@api_key_required
def api_upsert_guild_messages(guild_id: str):
    data = request.get_json(silent=True) or {}
    messages = data.get("messages") or []
    if not isinstance(messages, list):
        return jsonify({"ok": False, "error": "messages_must_be_list"}), 400
    result = upsert_guild_messages(
        guild_id,
        messages,
        insert_only=bool(data.get("insert_only")),
    )
    return jsonify({"ok": True, **result})


@app.post("/api/guild/<guild_id>/messages/<channel_id>/<message_id>/delete")
@api_key_required
def api_mark_guild_message_deleted(guild_id: str, channel_id: str, message_id: str):
    mark_guild_message_deleted(guild_id, channel_id, message_id)
    return jsonify({"ok": True})


@app.get("/api/guild/<guild_id>/birthdays/today")
@api_key_required
def api_get_birthdays_today(guild_id: str):
    return jsonify(get_birthdays_today(guild_id))


@app.get("/api/guild/<guild_id>/birthdays/<user_id>")
@api_key_required
def api_get_birthday(guild_id: str, user_id: str):
    b = get_birthday(guild_id, user_id)
    if not b:
        return jsonify({"ok": False}), 404
    return jsonify(b)


@app.route("/api/guild/<guild_id>/birthdays/<user_id>", methods=["PUT"])
@api_key_required
def api_set_birthday(guild_id: str, user_id: str):
    data = request.get_json(silent=True) or {}
    set_birthday(guild_id, user_id, data["day"], data["month"], data.get("year"))
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/birthdays/<user_id>")
@api_key_required
def api_delete_birthday(guild_id: str, user_id: str):
    delete_birthday(guild_id, user_id)
    return jsonify({"ok": True})


@app.post("/api/guild/<guild_id>/birthdays/<user_id>/congrats")
@api_key_required
def api_mark_birthday_congrats(guild_id: str, user_id: str):
    mark_birthday_congrats(guild_id, user_id)
    return jsonify({"ok": True})


@app.get("/api/guild/<guild_id>/bot_messages")
@api_key_required
def api_get_bot_messages(guild_id: str):
    message_type = request.args.get("message_type")
    return jsonify(list_bot_messages(guild_id, message_type))


@app.put("/api/guild/<guild_id>/bot_messages/<message_type>/<message_id>")
@api_key_required
def api_upsert_bot_message(guild_id: str, message_type: str, message_id: str):
    data = request.get_json(silent=True) or {}
    row = upsert_bot_message(
        guild_id,
        message_type,
        message_id,
        str(data["channel_id"]) if data.get("channel_id") else None,
        str(data["meta_key"]) if data.get("meta_key") else None,
    )
    return jsonify(row)


@app.delete("/api/guild/<guild_id>/bot_messages/<message_type>/<message_id>")
@api_key_required
def api_delete_bot_message(guild_id: str, message_type: str, message_id: str):
    delete_bot_message(guild_id, message_type, message_id)
    return jsonify({"ok": True})


# -- Warnings --


@app.get("/api/guild/<guild_id>/warnings/<user_id>")
@api_key_required
def api_get_warnings(guild_id: str, user_id: str):
    return jsonify(get_warnings(guild_id, user_id))


@app.post("/api/guild/<guild_id>/warnings")
@api_key_required
def api_add_warning(guild_id: str):
    data = request.get_json(silent=True) or {}
    w = add_warning(
        guild_id, data["user_id"], data["moderator_id"], data.get("reason", "")
    )
    return jsonify(w)


@app.delete("/api/guild/<guild_id>/warnings/<int:warning_id>")
@api_key_required
def api_remove_warning(guild_id: str, warning_id: int):
    remove_warning(warning_id)
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/warnings/user/<user_id>")
@api_key_required
def api_clear_warnings(guild_id: str, user_id: str):
    count = clear_warnings(guild_id, user_id)
    return jsonify({"ok": True, "deleted": count})


# -- Counting --


@app.get("/api/guild/<guild_id>/counting")
@api_key_required
def api_get_counting(guild_id: str):
    c = get_counting(guild_id)
    if not c:
        return jsonify({"ok": False}), 404
    return jsonify(c)


@app.route("/api/guild/<guild_id>/counting", methods=["PUT"])
@api_key_required
def api_set_counting(guild_id: str):
    data = request.get_json(silent=True) or {}
    set_counting(guild_id, **data)
    return jsonify({"ok": True})


@app.get("/api/guild/<guild_id>/counting/stats/<user_id>")
@api_key_required
def api_get_counting_stats(guild_id: str, user_id: str):
    s = get_counting_stats(guild_id, user_id)
    if not s:
        return jsonify({"ok": False}), 404
    return jsonify(s)


@app.route("/api/guild/<guild_id>/counting/stats/<user_id>", methods=["PUT"])
@api_key_required
def api_set_counting_stats(guild_id: str, user_id: str):
    data = request.get_json(silent=True) or {}
    set_counting_stats(guild_id, user_id, **data)
    return jsonify({"ok": True})


@app.get("/api/guild/<guild_id>/counting/leaderboard")
@api_key_required
def api_get_counting_leaderboard(guild_id: str):
    limit = request.args.get("limit", 10, type=int)
    return jsonify(get_counting_leaderboard(guild_id, limit))


# -- Auto Publisher --


@app.get("/api/guild/<guild_id>/auto_publisher")
@api_key_required
def api_get_auto_publisher(guild_id: str):
    return jsonify(get_auto_publisher_channels(guild_id))


@app.post("/api/guild/<guild_id>/auto_publisher")
@api_key_required
def api_add_auto_publisher(guild_id: str):
    data = request.get_json(silent=True) or {}
    add_auto_publisher_channel(guild_id, str(data["channel_id"]))
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/auto_publisher/<channel_id>")
@api_key_required
def api_remove_auto_publisher(guild_id: str, channel_id: str):
    remove_auto_publisher_channel(guild_id, channel_id)
    return jsonify({"ok": True})


# -- Selfroles --


@app.get("/api/guild/<guild_id>/selfroles")
@api_key_required
def api_get_selfroles(guild_id: str):
    return jsonify(get_all_selfrole_panels(guild_id))


@app.get("/api/guild/<guild_id>/selfroles/<message_id>")
@api_key_required
def api_get_selfrole(guild_id: str, message_id: str):
    panel = get_selfrole_panel(message_id)
    if not panel:
        return jsonify({"ok": False}), 404
    return jsonify(panel)


@app.post("/api/guild/<guild_id>/selfroles")
@api_key_required
def api_create_selfrole(guild_id: str):
    data = request.get_json(silent=True) or {}
    panel = create_selfrole_panel(
        guild_id,
        data["message_id"],
        data["channel_id"],
        data["title"],
        data.get("max_roles", 0),
        data.get("roles", {}),
    )
    return jsonify(panel)


@app.route("/api/guild/<guild_id>/selfroles/<message_id>/roles", methods=["PUT"])
@api_key_required
def api_add_selfrole_mapping(guild_id: str, message_id: str):
    data = request.get_json(silent=True) or {}
    add_selfrole_mapping(message_id, data["emoji"], data["role_id"])
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/selfroles/<message_id>/roles/<emoji>")
@api_key_required
def api_remove_selfrole_mapping(guild_id: str, message_id: str, emoji: str):
    remove_selfrole_mapping(message_id, emoji)
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/selfroles/<message_id>")
@api_key_required
def api_delete_selfrole(guild_id: str, message_id: str):
    delete_selfrole_panel(message_id)
    return jsonify({"ok": True})


# -- Server Stats --


@app.get("/api/guild/<guild_id>/server_stats")
@api_key_required
def api_get_server_stats(guild_id: str):
    return jsonify(get_server_stats(guild_id))


@app.route("/api/guild/<guild_id>/server_stats", methods=["PUT"])
@api_key_required
def api_set_server_stats(guild_id: str):
    data = request.get_json(silent=True) or {}
    category_id = data.pop("category_id", None)
    set_server_stats(guild_id, category_id, data)
    return jsonify({"ok": True})


# -- Log Channels --


@app.get("/api/guild/<guild_id>/log_channels")
@api_key_required
def api_get_log_channels(guild_id: str):
    return jsonify(get_all_log_channels(guild_id))


@app.get("/api/guild/<guild_id>/log_channels/<log_type>")
@api_key_required
def api_get_log_channel(guild_id: str, log_type: str):
    ch = get_log_channel(guild_id, log_type)
    if not ch:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "channel_id": ch})


@app.route("/api/guild/<guild_id>/log_channels/<log_type>", methods=["PUT"])
@api_key_required
def api_set_log_channel(guild_id: str, log_type: str):
    data = request.get_json(silent=True) or {}
    set_log_channel(guild_id, log_type, str(data["channel_id"]))
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/log_channels/<log_type>")
@api_key_required
def api_remove_log_channel(guild_id: str, log_type: str):
    remove_log_channel(guild_id, log_type)
    return jsonify({"ok": True})


# -- Twitch Config --


@app.get("/api/guild/<guild_id>/twitch_config")
@api_key_required
def api_get_twitch_config(guild_id: str):
    tc = get_twitch_config(guild_id)
    if not tc:
        return jsonify({"ok": False}), 404
    return jsonify(tc)


@app.route("/api/guild/<guild_id>/twitch_config", methods=["PUT"])
@api_key_required
def api_set_twitch_config(guild_id: str):
    data = request.get_json(silent=True) or {}
    set_twitch_config(guild_id, **data)
    return jsonify({"ok": True})


@app.delete("/api/guild/<guild_id>/twitch_config")
@api_key_required
def api_remove_twitch_config(guild_id: str):
    remove_twitch_config(guild_id)
    return jsonify({"ok": True})


# -- Tickets API --


@app.get("/api/tickets")
@api_key_required
def api_list_tickets():
    q = request.args.get("q", "")
    limit = request.args.get("limit", 200, type=int)
    return jsonify(list_tickets(q=q, limit=limit))


@app.get("/api/tickets/<ticket_id>")
@api_key_required
def api_get_ticket(ticket_id: str):
    t = get_ticket(ticket_id)
    if not t:
        return jsonify({"ok": False}), 404
    return jsonify(t)


@app.post("/api/tickets")
@api_key_required
def api_upsert_ticket():
    data = request.get_json(silent=True) or {}
    if not data.get("ticket_id"):
        return jsonify({"ok": False, "error": "ticket_id missing"}), 400
    upsert_ticket(data)
    return jsonify({"ok": True, "ticket_id": data["ticket_id"]})


@app.post("/api/tickets/close")
@api_key_required
def api_ticket_close():
    data = request.get_json(silent=True) or {}
    ticket_id = str(data.get("ticket_id") or "").strip()
    if not ticket_id:
        return jsonify({"ok": False, "error": "ticket_id missing"}), 400

    transcript_html = _render_transcript_html(data)
    transcript_rel = ""
    if transcript_html:
        transcript_rel = f"data/transcripts/{ticket_id}.html"
        transcript_abs = (Path(__file__).resolve().parent / transcript_rel).resolve()
        transcript_abs.parent.mkdir(parents=True, exist_ok=True)
        transcript_abs.write_text(transcript_html, encoding="utf-8")

    upsert_ticket(
        {
            "ticket_id": ticket_id,
            "guild_id": data.get("guild_id"),
            "channel_id": data.get("channel_id") or ticket_id,
            "creator_user_id": str(
                data.get("creator_user_id") or data.get("creator_id") or ""
            ),
            "creator_username": data.get("creator_name")
            or data.get("creator_username"),
            "status": data.get("status") or "closed",
            "subject": data.get("subject") or data.get("category_label") or "",
            "category": data.get("category") or data.get("category_label") or "",
            "closed_at": data.get("closed_at") or "",
            "closed_by_id": data.get("closed_by_id"),
            "closed_by_name": data.get("closed_by_name"),
            "close_reason": data.get("close_reason"),
            "transcript_path": transcript_rel or None,
            "transcript_url": data.get("transcript_url"),
        }
    )

    return jsonify(
        {"ok": True, "ticket_id": ticket_id, "transcript_path": transcript_rel}
    )


# -- Ticket Messages API --


@app.get("/api/tickets/<ticket_id>/messages")
@api_key_required
def api_get_ticket_messages(ticket_id: str):
    return jsonify(get_ticket_messages(ticket_id))


@app.post("/api/tickets/<ticket_id>/messages")
@api_key_required
def api_add_ticket_message(ticket_id: str):
    data = request.get_json(silent=True) or {}
    msg = add_ticket_message(
        ticket_id,
        data["author_id"],
        data["author_name"],
        data["content"],
        data.get("source", "discord"),
        data.get("discord_message_id"),
    )
    return jsonify(msg)


# -- Ticket Logs API --


@app.post("/api/ticket_logs")
@api_key_required
def api_ticket_logs():
    data = request.get_json(silent=True) or {}
    if not data.get("ticket_id"):
        return jsonify({"ok": False, "error": "ticket_id missing"}), 400
    insert_ticket_log(data)
    return jsonify({"ok": True})


# legacy alias
@app.post("/api/logs")
@api_key_required
def api_logs_legacy():
    data = request.get_json(silent=True) or {}
    if not data.get("ticket_id"):
        return jsonify({"ok": False, "error": "ticket_id missing"}), 400
    insert_ticket_log(data)
    return jsonify({"ok": True})


# -- Roles API (for external use) --


@app.get("/api/guild/<guild_id>/roles")
@api_key_required
def api_get_roles(guild_id: str):
    return jsonify(list_roles(guild_id))


# -- Close Reasons API --


@app.get("/api/guild/<guild_id>/close_reasons")
@api_key_required
def api_get_close_reasons(guild_id: str):
    return jsonify(list_close_reasons(guild_id))


@app.post("/api/guild/<guild_id>/close_reasons")
@api_key_required
def api_add_close_reason(guild_id: str):
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"ok": False, "error": "label missing"}), 400
    r = add_close_reason(guild_id, label, data.get("sort_order", 0))
    return jsonify(r)


@app.delete("/api/guild/<guild_id>/close_reasons/<int:reason_id>")
@api_key_required
def api_delete_close_reason(guild_id: str, reason_id: int):
    delete_close_reason(reason_id)
    return jsonify({"ok": True})


# ---------------- STARTUP ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=True)
