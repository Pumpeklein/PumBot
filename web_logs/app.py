from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from functools import wraps
from html import escape
from pathlib import Path

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
        add_auto_publisher_channel,
        add_close_reason,
        add_selfrole_mapping,
        add_ticket_message,
        add_warning,
        count_birthdays,
        count_counting_leaderboard,
        count_guild_members,
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
        get_guild_members_panel_guild_id,
        get_guild_message_overview,
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
        set_birthday,
        set_config,
        set_counting,
        set_counting_stats,
        set_log_channel,
        set_server_stats,
        set_twitch_config,
        sync_guild_members,
        mark_guild_message_deleted,
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
    )
    from .token_utils import verify_transcript_token
    from .datetime_format import format_berlin_date, format_berlin_datetime
except ImportError:
    from config import Config, DEFAULT_GUILD_ID, ensure_dirs
    from db import (
        ALL_PERMISSIONS,
        add_auto_publisher_channel,
        add_close_reason,
        add_selfrole_mapping,
        add_ticket_message,
        add_warning,
        count_birthdays,
        count_counting_leaderboard,
        count_guild_members,
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
        get_guild_members_panel_guild_id,
        get_guild_message_overview,
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
        set_birthday,
        set_config,
        set_counting,
        set_counting_stats,
        set_log_channel,
        set_server_stats,
        set_twitch_config,
        sync_guild_members,
        mark_guild_message_deleted,
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
    )
    from token_utils import verify_transcript_token
    from datetime_format import format_berlin_date, format_berlin_datetime

ensure_dirs()

app = Flask(__name__)
app.secret_key = Config.FLASK_SECRET_KEY
app.jinja_env.filters["date_de"] = format_berlin_date
app.jinja_env.filters["datetime_de"] = format_berlin_datetime

init_db()


def create_app() -> Flask:
    return app


def _ctx() -> dict:
    u = current_user()
    if not u:
        return {"username": None, "avatar": None, "permissions": set()}
    return {
        "username": u["username"],
        "avatar": u.get("avatar"),
        "permissions": u["permissions"],
    }


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
        return {"display_name": None, "avatar_url": None, "username": None, "status": None}
    member = get_guild_member(guild_id, str(user_id))
    if not member:
        return {
            "display_name": str(user_id),
            "avatar_url": None,
            "username": None,
            "status": None,
        }
    return {
        "display_name": member.get("display_name") or member.get("username") or str(user_id),
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


def _active_panel_guild_id() -> str:
    requested_guild_id = (request.args.get("guild_id") or "").strip()
    if requested_guild_id:
        return requested_guild_id

    stored_guild_id = get_guild_members_panel_guild_id(DEFAULT_GUILD_ID)
    if stored_guild_id != DEFAULT_GUILD_ID or list_guild_members(stored_guild_id, limit=1):
        return stored_guild_id

    bot = app.config.get("DISCORD_BOT")
    if bot and getattr(bot, "is_ready", lambda: False)():
        guilds = getattr(bot, "guilds", []) or []
        if guilds:
            return str(guilds[0].id)

    return stored_guild_id


def _pagination_args(default_page_size: int = 10) -> tuple[int, int, int]:
    page = request.args.get("page", 1, type=int) or 1
    page_size = request.args.get("page_size", default_page_size, type=int) or default_page_size
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


# ════════════════ API KEY SECURITY ════════════════


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


# ════════════════ AUTH ROUTES ════════════════


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


# ════════════════ WEB PAGES ════════════════


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
    return render_template(
        "tickets.html",
        q=q,
        total=count_tickets(q=q),
        active_page="tickets",
        **ctx,
    )


@app.get("/tickets/<ticket_id>")
@login_required
def ticket_detail(ticket_id: str):
    ctx = _ctx()
    t = get_ticket(ticket_id)
    if not t:
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
    if not t or not t.get("transcript_path"):
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


# ── Roles Management Page ──


@app.get("/roles")
@permission_required("roles.manage")
def roles_page():
    ctx = _ctx()
    roles = list_roles(DEFAULT_GUILD_ID)
    return render_template(
        "roles.html",
        roles=roles,
        all_permissions=ALL_PERMISSIONS,
        active_page="roles",
        **ctx,
    )


@app.post("/roles/create")
@permission_required("roles.manage")
def roles_create():
    discord_role_id = (request.form.get("discord_role_id") or "").strip()
    role_name = (request.form.get("role_name") or "").strip()
    perms = request.form.getlist("permissions")
    if not discord_role_id or not role_name:
        return redirect(url_for("roles_page"))
    create_role(DEFAULT_GUILD_ID, discord_role_id, role_name, perms)
    return redirect(url_for("roles_page"))


@app.post("/roles/<int:role_id>/update")
@permission_required("roles.manage")
def roles_update(role_id: int):
    role_name = (request.form.get("role_name") or "").strip()
    perms = request.form.getlist("permissions")
    update_role(role_id, role_name=role_name or None, permissions=perms)
    return redirect(url_for("roles_page"))


@app.post("/roles/<int:role_id>/delete")
@permission_required("roles.manage")
def roles_delete(role_id: int):
    delete_role(role_id)
    return redirect(url_for("roles_page"))


# ── Ticket Messages JSON (web session auth) ──


@app.get("/tickets/<ticket_id>/messages.json")
@login_required
def ticket_messages_json(ticket_id: str):
    messages = get_ticket_messages(ticket_id)
    return jsonify(_format_date_fields(messages, "created_at"))


# ── Ticket Reply from Web ──


@app.post("/tickets/<ticket_id>/reply")
@login_required
def ticket_reply_web(ticket_id: str):
    if not has_permission("tickets.reply"):
        abort(403)
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


# ── Close Ticket from Web ──


@app.post("/tickets/<ticket_id>/close")
@login_required
def ticket_close_web(ticket_id: str):
    if not has_permission("tickets.close"):
        abort(403)
    t = get_ticket(ticket_id)
    if not t or t.get("status") == "closed":
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


# ── Close Reasons Config Page ──


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


# ── Counting Overview Page ──


@app.get("/counting")
@permission_required("config.manage")
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
@permission_required("config.manage")
def counting_set_channel():
    channel_id = (request.form.get("channel_id") or "").strip()
    if channel_id:
        set_counting(DEFAULT_GUILD_ID, channel_id=channel_id)
    return redirect(url_for("counting_page"))


@app.post("/counting/reset")
@permission_required("config.manage")
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
    active_count = count_guild_members(guild_id, status="active")
    left_count = count_guild_members(guild_id, status="left")
    return render_template(
        "users.html",
        q=q,
        guild_id=guild_id,
        status=status,
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
    message_stats = get_user_message_stats(guild_id, user_id)
    channel_stats = get_user_channel_message_stats(guild_id, user_id)
    ticket_stats = get_ticket_stats_for_user(guild_id, user_id)
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
        message_stats=_format_date_fields([message_stats], "last_message_at")[0],
        channel_stats=_format_date_fields(channel_stats, "last_message_at"),
        ticket_stats=_format_date_fields([ticket_stats], "last_ticket_at")[0],
        guild_id=guild_id,
        active_page="users",
        **ctx,
    )


@app.get("/stats")
@permission_required("users.view")
def stats_page():
    ctx = _ctx()
    guild_id = _active_panel_guild_id()
    q = request.args.get("q", "").strip()
    user_id = request.args.get("user_id", "").strip()
    channel_id = request.args.get("channel_id", "").strip()
    overview = get_guild_message_overview(guild_id)
    return render_template(
        "stats.html",
        guild_id=guild_id,
        q=q,
        filter_user_id=user_id,
        filter_channel_id=channel_id,
        filter_users=list_message_filter_users(guild_id),
        filter_channels=list_message_filter_channels(guild_id),
        overview={
            **overview,
            "totals": _format_date_fields([overview.get("totals") or {}], "last_message_at")[0],
            "top_channels": _format_date_fields(overview.get("top_channels") or [], "last_message_at"),
        },
        active_page="stats",
        **ctx,
    )


# ── Birthdays Overview Page ──


@app.get("/birthdays")
@permission_required("config.manage")
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
    return render_template(
        "birthdays.html",
        birthday_count=count_birthdays(birthdays_guild_id),
        birthday_channel=birthday_channel,
        birthday_messages=birthday_messages,
        birthdays_guild_id=birthdays_guild_id,
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
@permission_required("config.manage")
def birthdays_set_channel():
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    channel_id = (request.form.get("channel_id") or "").strip()
    if channel_id:
        set_config(birthdays_guild_id, "birthday_channel_id", channel_id)
    else:
        delete_config(birthdays_guild_id, "birthday_channel_id")
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/<user_id>/set")
@permission_required("config.manage")
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
@permission_required("config.manage")
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
@permission_required("config.manage")
def birthdays_delete(user_id: str):
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    delete_birthday(birthdays_guild_id, user_id)
    _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/messages/add")
@permission_required("config.manage")
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
@permission_required("config.manage")
def birthdays_delete_message(message_id: str):
    birthdays_guild_id = get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    delete_bot_message(birthdays_guild_id, "birthday_list", message_id)
    _trigger_birthday_list_refresh(birthdays_guild_id)
    return redirect(url_for("birthdays_page"))


# ── Warnings Overview Page ──


@app.get("/warnings")
@permission_required("users.warn")
def warnings_page():
    ctx = _ctx()
    q_user = request.args.get("user_id", "").strip()
    cache: dict[str, str | None] = {}
    return render_template(
        "warnings.html",
        warning_count=count_warnings(DEFAULT_GUILD_ID, q_user or None),
        q_user=q_user,
        q_user_display_name=_resolve_display_name(q_user, cache, guild_id=DEFAULT_GUILD_ID) if q_user else None,
        guild_id=DEFAULT_GUILD_ID,
        active_page="warnings",
        **ctx,
    )


@app.post("/warnings/<int:warning_id>/delete")
@permission_required("users.warn")
def warnings_delete(warning_id: int):
    remove_warning(warning_id)
    return redirect(url_for("warnings_page"))


# ── Log Channels Config Page ──


@app.get("/log-channels")
@permission_required("config.manage")
def log_channels_page():
    ctx = _ctx()
    channels = get_all_log_channels(DEFAULT_GUILD_ID)
    log_types = ["voice_log", "user_log", "server_log", "message_log", "welcome_log"]
    return render_template(
        "log_channels.html",
        channels=channels,
        log_types=log_types,
        active_page="log_channels",
        **ctx,
    )


@app.post("/log-channels/set")
@permission_required("config.manage")
def log_channels_set():
    log_type = (request.form.get("log_type") or "").strip()
    channel_id = (request.form.get("channel_id") or "").strip()
    if log_type and channel_id:
        set_log_channel(DEFAULT_GUILD_ID, log_type, channel_id)
    return redirect(url_for("log_channels_page"))


@app.post("/log-channels/<log_type>/delete")
@permission_required("config.manage")
def log_channels_delete(log_type: str):
    remove_log_channel(DEFAULT_GUILD_ID, log_type)
    return redirect(url_for("log_channels_page"))


# ── Auto Publisher Config Page ──


@app.get("/auto-publisher")
@permission_required("config.manage")
def auto_publisher_page():
    ctx = _ctx()
    channels = get_auto_publisher_channels(DEFAULT_GUILD_ID)
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


# ── Server Stats Config Page ──


@app.get("/server-stats")
@permission_required("config.manage")
def server_stats_page():
    ctx = _ctx()
    stats = get_server_stats(DEFAULT_GUILD_ID)
    stat_types = ["all", "members", "bots", "channels", "roles"]
    return render_template(
        "server_stats.html",
        stats=stats,
        stat_types=stat_types,
        active_page="server_stats",
        **ctx,
    )


@app.post("/server-stats/save")
@permission_required("config.manage")
def server_stats_save():
    category_id = (request.form.get("category_id") or "").strip() or None
    stats = {}
    for key in ["all", "members", "bots", "channels", "roles"]:
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
    page, page_size, offset = _pagination_args()
    rows = []
    for ticket in list_tickets(q=q, limit=page_size, offset=offset):
        guild_id = ticket.get("guild_id") or DEFAULT_GUILD_ID
        item = _attach_member_profile(ticket, guild_id, "creator_user_id", "creator")
        item["detail_url"] = url_for("ticket_detail", ticket_id=item["ticket_id"])
        rows.append(item)
    return _paginated_response(rows, count_tickets(q=q), page, page_size)


@app.get("/panel-api/users/<user_id>/tickets")
@login_required
def panel_api_user_tickets(user_id: str):
    guild_id = _active_panel_guild_id()
    page, page_size, offset = _pagination_args()
    rows = []
    for ticket in list_tickets_for_user(
        guild_id, user_id, limit=page_size, offset=offset
    ):
        item = dict(ticket)
        item["detail_url"] = url_for("ticket_detail", ticket_id=item["ticket_id"])
        rows.append(item)
    return _paginated_response(
        rows, count_tickets_for_user(guild_id, user_id), page, page_size
    )


@app.get("/panel-api/users")
@permission_required("users.view")
def panel_api_users():
    guild_id = _active_panel_guild_id()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    if status not in {"all", "active", "left"}:
        status = "all"
    page, page_size, offset = _pagination_args()
    rows = list_guild_members(
        guild_id, q=q, status=status, limit=page_size, offset=offset
    )
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
        row["roles_label"] = ", ".join(role_names[:3]) if role_names else "-"
        if len(role_names) > 3:
            row["roles_label"] += f" +{len(role_names) - 3}"
    return _paginated_response(
        _format_date_fields(rows, "joined_at", "left_at", "first_seen_at", "last_seen_at", "updated_at", "last_message_at", "status_updated_at"),
        count_guild_members(guild_id, q=q, status=status),
        page,
        page_size,
    )


@app.get("/panel-api/messages")
@permission_required("users.view")
def panel_api_messages():
    guild_id = request.args.get("guild_id") or _active_panel_guild_id()
    user_id = request.args.get("user_id", "").strip() or None
    channel_id = request.args.get("channel_id", "").strip() or None
    q = request.args.get("q", "").strip()
    include_deleted = request.args.get("include_deleted") == "1"
    page, page_size, offset = _pagination_args()
    rows = []
    for message in list_guild_messages(
        guild_id,
        user_id=user_id,
        channel_id=channel_id,
        q=q,
        include_deleted=include_deleted,
        limit=page_size,
        offset=offset,
    ):
        item = dict(message)
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
        ),
        page,
        page_size,
    )


@app.get("/panel-api/birthdays")
@permission_required("config.manage")
def panel_api_birthdays():
    guild_id = request.args.get("guild_id") or get_birthdays_panel_guild_id(DEFAULT_GUILD_ID)
    page, page_size, offset = _pagination_args()
    month_names = {
        1: "Januar", 2: "Februar", 3: "März", 4: "April",
        5: "Mai", 6: "Juni", 7: "Juli", 8: "August",
        9: "September", 10: "Oktober", 11: "November", 12: "Dezember",
    }
    rows = []
    for row in get_birthdays(guild_id, limit=page_size, offset=offset):
        item = _attach_member_profile(row, guild_id, "user_id", "user")
        item["date_label"] = f"{int(item['day']):02d}.{int(item['month']):02d}" + (
            f".{item['year']}" if item.get("year") else ""
        )
        item["month_name"] = month_names.get(item.get("month"), "?")
        item["delete_url"] = url_for("birthdays_delete", user_id=item["user_id"])
        rows.append(item)
    return _paginated_response(rows, count_birthdays(guild_id), page, page_size)


@app.get("/panel-api/warnings")
@permission_required("users.warn")
def panel_api_warnings():
    guild_id = request.args.get("guild_id") or DEFAULT_GUILD_ID
    q_user = request.args.get("user_id", "").strip()
    page, page_size, offset = _pagination_args()
    if q_user:
        warnings = get_warnings(guild_id, q_user, limit=page_size, offset=offset)
    else:
        warnings = list_all_warnings(guild_id, limit=page_size, offset=offset)
    rows = []
    for warning in warnings:
        item = _attach_member_profile(warning, guild_id, "user_id", "user")
        item = _attach_member_profile(item, guild_id, "moderator_id", "moderator")
        item["delete_url"] = url_for("warnings_delete", warning_id=item["id"])
        rows.append(item)
    return _paginated_response(
        rows, count_warnings(guild_id, q_user or None), page, page_size
    )


@app.get("/panel-api/counting/leaderboard")
@permission_required("config.manage")
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


# ════════════════════════════════════════════════════════
#  API ENDPOINTS (called by the bot via ApiClient)
# ════════════════════════════════════════════════════════

# ── Guild Config ──


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


# ── Birthdays ──


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
    result = upsert_guild_messages(guild_id, messages)
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


# ── Warnings ──


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


# ── Counting ──


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


# ── Auto Publisher ──


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


# ── Selfroles ──


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


# ── Server Stats ──


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


# ── Log Channels ──


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


# ── Twitch Config ──


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


# ── Tickets API ──


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


# ── Ticket Messages API ──


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


# ── Ticket Logs API ──


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


# ── Roles API (for external use) ──


@app.get("/api/guild/<guild_id>/roles")
@api_key_required
def api_get_roles(guild_id: str):
    return jsonify(list_roles(guild_id))


# ── Close Reasons API ──


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


# ════════════════ STARTUP ════════════════

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=Config.PORT, debug=True)
