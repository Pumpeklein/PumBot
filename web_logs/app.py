from __future__ import annotations

import asyncio
import json
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
        clear_warnings,
        create_role,
        create_selfrole_panel,
        delete_birthday,
        delete_close_reason,
        delete_config,
        delete_role,
        delete_selfrole_panel,
        get_all_log_channels,
        get_all_selfrole_panels,
        get_auto_publisher_channels,
        get_birthday,
        get_birthdays,
        get_birthdays_today,
        get_config,
        get_counting,
        get_counting_leaderboard,
        get_counting_stats,
        get_log_channel,
        get_selfrole_panel,
        get_server_stats,
        get_ticket,
        get_ticket_messages,
        get_twitch_config,
        get_warnings,
        init_db,
        insert_ticket_log,
        list_all_warnings,
        list_close_reasons,
        list_logs_for_ticket,
        list_roles,
        list_tickets,
        mark_birthday_congrats,
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
except ImportError:
    from config import Config, DEFAULT_GUILD_ID, ensure_dirs
    from db import (
        ALL_PERMISSIONS,
        add_auto_publisher_channel,
        add_close_reason,
        add_selfrole_mapping,
        add_ticket_message,
        add_warning,
        clear_warnings,
        create_role,
        create_selfrole_panel,
        delete_birthday,
        delete_close_reason,
        delete_config,
        delete_role,
        delete_selfrole_panel,
        get_all_log_channels,
        get_all_selfrole_panels,
        get_auto_publisher_channels,
        get_birthday,
        get_birthdays,
        get_birthdays_today,
        get_config,
        get_counting,
        get_counting_leaderboard,
        get_counting_stats,
        get_log_channel,
        get_selfrole_panel,
        get_server_stats,
        get_ticket,
        get_ticket_messages,
        get_twitch_config,
        get_warnings,
        init_db,
        insert_ticket_log,
        list_all_warnings,
        list_close_reasons,
        list_logs_for_ticket,
        list_roles,
        list_tickets,
        mark_birthday_congrats,
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

ensure_dirs()

app = Flask(__name__)
app.secret_key = Config.FLASK_SECRET_KEY

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
        return transcript_html
    transcript_text = data.get("transcript_text") or ""
    if transcript_text:
        return f"<pre>{escape(transcript_text)}</pre>"
    return ""


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
    limit_raw = request.args.get("limit", "200")
    try:
        limit = max(1, min(1000, int(limit_raw)))
    except ValueError:
        limit = 200
    items = list_tickets(q=q, limit=limit)
    return render_template(
        "tickets.html", items=items, q=q, limit=limit,
        active_page="tickets", **ctx,
    )


@app.get("/tickets/<ticket_id>")
@login_required
def ticket_detail(ticket_id: str):
    ctx = _ctx()
    t = get_ticket(ticket_id)
    if not t:
        abort(404)
    logs = list_logs_for_ticket(ticket_id, limit=200)
    messages = get_ticket_messages(ticket_id)
    close_reasons = list_close_reasons(DEFAULT_GUILD_ID)
    return render_template(
        "ticket_detail.html", t=t, logs=logs, messages=messages,
        close_reasons=close_reasons, active_page="tickets", **ctx,
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
    html = path.read_text(encoding="utf-8")
    ctx = _ctx()
    return render_template(
        "transcript.html", ticket_id=ticket_id, html=html, **ctx,
    )


@app.get("/t/<ticket_id>")
def public_transcript(ticket_id: str):
    token = request.args.get("token") or ""
    if not token:
        if current_user():
            return ticket_transcript(ticket_id)
        abort(403)
    data = verify_transcript_token(app.secret_key, token, max_age_seconds=60 * 60 * 24 * 7)
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
    html = path.read_text(encoding="utf-8")
    ctx = _ctx()
    return render_template(
        "transcript.html", ticket_id=ticket_id, html=html, **ctx,
    )


# ── Roles Management Page ──

@app.get("/roles")
@permission_required("roles.manage")
def roles_page():
    ctx = _ctx()
    roles = list_roles(DEFAULT_GUILD_ID)
    return render_template(
        "roles.html", roles=roles, all_permissions=ALL_PERMISSIONS,
        active_page="roles", **ctx,
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
    return jsonify(messages)


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


async def _send_discord_reply(bot, channel_id: int, username: str, content: str) -> None:
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
    upsert_ticket({
        "ticket_id": ticket_id,
        "status": "closed",
        "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "closed_by_id": u["discord_id"],
        "closed_by_name": u["username"],
        "close_reason": reason,
    })

    # Let the bot's TicketSystemCog.close_ticket handle the rest
    # (transcript, logs, DM, archive, channel delete)
    bot = app.config.get("DISCORD_BOT")
    if bot and bot.is_ready():
        channel_id = t.get("channel_id")
        if channel_id:
            try:
                loop = bot.loop
                asyncio.run_coroutine_threadsafe(
                    _close_discord_ticket(bot, int(channel_id), u["discord_id"], reason),
                    loop,
                )
            except Exception:
                pass

    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


async def _close_discord_ticket(bot, channel_id: int, closer_discord_id: str, reason: str) -> None:
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
        "close_reasons.html", reasons=reasons,
        active_page="close_reasons", **ctx,
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
    leaderboard = get_counting_leaderboard(DEFAULT_GUILD_ID, limit=50)
    return render_template(
        "counting.html", state=state, leaderboard=leaderboard,
        active_page="counting", **ctx,
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


# ── Birthdays Overview Page ──

@app.get("/birthdays")
@permission_required("config.manage")
def birthdays_page():
    ctx = _ctx()
    all_birthdays = get_birthdays(DEFAULT_GUILD_ID)
    birthday_channel = get_config(DEFAULT_GUILD_ID, "birthday_channel_id")
    return render_template(
        "birthdays.html", birthdays=all_birthdays,
        birthday_channel=birthday_channel,
        active_page="birthdays", **ctx,
    )


@app.post("/birthdays/set-channel")
@permission_required("config.manage")
def birthdays_set_channel():
    channel_id = (request.form.get("channel_id") or "").strip()
    if channel_id:
        set_config(DEFAULT_GUILD_ID, "birthday_channel_id", channel_id)
    else:
        delete_config(DEFAULT_GUILD_ID, "birthday_channel_id")
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/<user_id>/set")
@permission_required("config.manage")
def birthdays_set(user_id: str):
    day = request.form.get("day", type=int)
    month = request.form.get("month", type=int)
    year = request.form.get("year", type=int) or None
    if day and month:
        set_birthday(DEFAULT_GUILD_ID, user_id, day, month, year)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/add")
@permission_required("config.manage")
def birthdays_add():
    user_id = (request.form.get("user_id") or "").strip()
    day = request.form.get("day", type=int)
    month = request.form.get("month", type=int)
    year = request.form.get("year", type=int) or None
    if user_id and day and month:
        set_birthday(DEFAULT_GUILD_ID, user_id, day, month, year)
    return redirect(url_for("birthdays_page"))


@app.post("/birthdays/<user_id>/delete")
@permission_required("config.manage")
def birthdays_delete(user_id: str):
    delete_birthday(DEFAULT_GUILD_ID, user_id)
    return redirect(url_for("birthdays_page"))


# ── Warnings Overview Page ──

@app.get("/warnings")
@permission_required("users.warn")
def warnings_page():
    ctx = _ctx()
    q_user = request.args.get("user_id", "").strip()
    if q_user:
        warns = get_warnings(DEFAULT_GUILD_ID, q_user)
    else:
        warns = list_all_warnings(DEFAULT_GUILD_ID, limit=200)
    return render_template(
        "warnings.html", warnings=warns, q_user=q_user,
        active_page="warnings", **ctx,
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
        "log_channels.html", channels=channels, log_types=log_types,
        active_page="log_channels", **ctx,
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
        "auto_publisher.html", channels=channels,
        active_page="auto_publisher", **ctx,
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
        "server_stats.html", stats=stats, stat_types=stat_types,
        active_page="server_stats", **ctx,
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


# ── Warnings ──

@app.get("/api/guild/<guild_id>/warnings/<user_id>")
@api_key_required
def api_get_warnings(guild_id: str, user_id: str):
    return jsonify(get_warnings(guild_id, user_id))


@app.post("/api/guild/<guild_id>/warnings")
@api_key_required
def api_add_warning(guild_id: str):
    data = request.get_json(silent=True) or {}
    w = add_warning(guild_id, data["user_id"], data["moderator_id"], data.get("reason", ""))
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
        guild_id, data["message_id"], data["channel_id"],
        data["title"], data.get("max_roles", 0), data.get("roles", {}),
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

    upsert_ticket({
        "ticket_id": ticket_id,
        "guild_id": data.get("guild_id"),
        "channel_id": data.get("channel_id") or ticket_id,
        "creator_user_id": str(data.get("creator_user_id") or data.get("creator_id") or ""),
        "creator_username": data.get("creator_name") or data.get("creator_username"),
        "status": data.get("status") or "closed",
        "subject": data.get("subject") or data.get("category_label") or "",
        "category": data.get("category") or data.get("category_label") or "",
        "closed_at": data.get("closed_at") or "",
        "closed_by_id": data.get("closed_by_id"),
        "closed_by_name": data.get("closed_by_name"),
        "close_reason": data.get("close_reason"),
        "transcript_path": transcript_rel or None,
        "transcript_url": data.get("transcript_url"),
    })

    return jsonify({"ok": True, "ticket_id": ticket_id, "transcript_path": transcript_rel})


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
    app.run(host="127.0.0.1", port=Config.PORT, debug=True)
