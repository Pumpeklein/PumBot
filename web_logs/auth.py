from __future__ import annotations

import logging
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import abort, redirect, request, session, url_for

try:
    from .config import Config, DEFAULT_GUILD_ID
    from .db import get_permissions_for_discord_roles, upsert_user
except ImportError:
    from config import Config, DEFAULT_GUILD_ID
    from db import get_permissions_for_discord_roles, upsert_user

logger = logging.getLogger("web_logs.auth")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN = "https://discord.com/api/oauth2/token"


def discord_login_url() -> str:
    params = {
        "client_id": Config.DISCORD_CLIENT_ID,
        "redirect_uri": Config.DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
    }
    return f"{DISCORD_OAUTH_AUTHORIZE}?{urlencode(params)}"


def exchange_code(code: str) -> dict | None:
    data = {
        "client_id": Config.DISCORD_CLIENT_ID,
        "client_secret": Config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": Config.DISCORD_REDIRECT_URI,
    }
    resp = requests.post(
        DISCORD_OAUTH_TOKEN,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if resp.status_code != 200:
        logger.error("exchange_code failed: %d %s", resp.status_code, resp.text)
        return None
    return resp.json()


def fetch_discord_user(access_token: str) -> dict | None:
    resp = requests.get(
        f"{DISCORD_API}/users/@me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    return resp.json()


def fetch_guild_member_roles(discord_user_id: str) -> list[str]:
    bot_token = Config.DISCORD_BOT_TOKEN
    if not bot_token:
        logger.warning("fetch_guild_member_roles: no bot token configured")
        return []
    resp = requests.get(
        f"{DISCORD_API}/guilds/{DEFAULT_GUILD_ID}/members/{discord_user_id}",
        headers={"Authorization": f"Bot {bot_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        logger.error("fetch_guild_member_roles failed: %d %s", resp.status_code, resp.text)
        return []
    return resp.json().get("roles", [])


def login_user_from_oauth(code: str) -> bool:
    try:
        token_data = exchange_code(code)
        if not token_data:
            logger.warning("login_user_from_oauth: exchange_code returned None")
            return False

        access_token = token_data.get("access_token")
        if not access_token:
            logger.warning("login_user_from_oauth: no access_token in response: %s", token_data)
            return False

        discord_user = fetch_discord_user(access_token)
        if not discord_user:
            logger.warning("login_user_from_oauth: fetch_discord_user returned None")
            return False

        discord_id = discord_user["id"]
        username = discord_user.get("global_name") or discord_user.get("username", "Unknown")
        avatar = discord_user.get("avatar")
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png"
            if avatar
            else None
        )

        upsert_user(discord_id, username, avatar_url)

        guild_roles = fetch_guild_member_roles(discord_id)
        permissions = get_permissions_for_discord_roles(DEFAULT_GUILD_ID, guild_roles)

        if not permissions:
            logger.warning("login_user_from_oauth: no permissions for user %s (roles: %s)", discord_id, guild_roles)
            return False

        session["discord_id"] = discord_id
        session["discord_username"] = username
        session["discord_avatar"] = avatar_url
        session["discord_roles"] = guild_roles
        session["permissions"] = list(permissions)
        return True
    except Exception:
        logger.exception("login_user_from_oauth unexpected error")
        return False


def current_user() -> dict | None:
    if "discord_id" not in session:
        return None
    return {
        "discord_id": session["discord_id"],
        "username": session["discord_username"],
        "avatar": session.get("discord_avatar"),
        "permissions": set(session.get("permissions", [])),
    }


def has_permission(permission: str) -> bool:
    u = current_user()
    if not u:
        return False
    perms = u["permissions"]
    return "admin" in perms or permission in perms


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def permission_required(permission: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user():
                return redirect(url_for("login"))
            if not has_permission(permission):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
