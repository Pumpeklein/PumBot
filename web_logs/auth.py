from __future__ import annotations

import logging
import time
from functools import wraps
from threading import Lock
from urllib.parse import urlencode

import requests
from flask import abort, redirect, request, session, url_for

try:
    from .config import Config, DEFAULT_GUILD_ID
    from .db import get_guild_member, get_permissions_for_discord_roles, get_user_by_discord_id, upsert_user
except ImportError:
    from config import Config, DEFAULT_GUILD_ID
    from db import get_guild_member, get_permissions_for_discord_roles, get_user_by_discord_id, upsert_user

logger = logging.getLogger("web_logs.auth")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN = "https://discord.com/api/oauth2/token"
DISPLAY_NAME_CACHE_TTL_SECONDS = 60 * 30
DISPLAY_NAME_ERROR_TTL_SECONDS = 60

_CACHE_MISS = object()
_display_name_cache: dict[str, tuple[float, str | None]] = {}
_display_name_rate_limited_until: dict[str, float] = {}
_display_name_cache_lock = Lock()


def _get_cached_display_name(discord_user_id: str) -> str | None | object:
    now = time.time()
    with _display_name_cache_lock:
        cached = _display_name_cache.get(discord_user_id)
        if not cached:
            return _CACHE_MISS
        expires_at, value = cached
        if expires_at <= now:
            _display_name_cache.pop(discord_user_id, None)
            return _CACHE_MISS
        return value


def _set_cached_display_name(
    discord_user_id: str,
    value: str | None,
    ttl_seconds: float = DISPLAY_NAME_CACHE_TTL_SECONDS,
) -> None:
    with _display_name_cache_lock:
        _display_name_cache[discord_user_id] = (time.time() + max(ttl_seconds, 0), value)


def _set_rate_limit_cooldown(discord_user_id: str, retry_after_seconds: float) -> None:
    with _display_name_cache_lock:
        _display_name_rate_limited_until[discord_user_id] = time.time() + max(
            retry_after_seconds, 0
        )


def _is_rate_limited(discord_user_id: str) -> bool:
    now = time.time()
    with _display_name_cache_lock:
        blocked_until = _display_name_rate_limited_until.get(discord_user_id, 0)
        if blocked_until <= now:
            _display_name_rate_limited_until.pop(discord_user_id, None)
            return False
        return True


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


def _discord_asset_url(user_id: str, asset_hash: str | None, asset_type: str) -> str | None:
    if not asset_hash:
        return None
    ext = "gif" if asset_hash.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/{asset_type}/{user_id}/{asset_hash}.{ext}"


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


def fetch_guild_member_display_name(discord_user_id: str) -> str | None:
    if not discord_user_id:
        return None

    memory_cached_name = _get_cached_display_name(discord_user_id)
    if memory_cached_name is not _CACHE_MISS:
        return memory_cached_name

    cached_member = get_guild_member(DEFAULT_GUILD_ID, discord_user_id)
    cached_name = cached_member.get("display_name") if cached_member else None
    if not cached_name:
        cached_user = get_user_by_discord_id(discord_user_id)
        cached_name = cached_user.get("discord_username") if cached_user else None
    if cached_name:
        _set_cached_display_name(discord_user_id, cached_name)
        return cached_name

    bot_token = Config.DISCORD_BOT_TOKEN
    if not bot_token:
        return cached_name
    if _is_rate_limited(discord_user_id):
        return cached_name

    resp = requests.get(
        f"{DISCORD_API}/guilds/{DEFAULT_GUILD_ID}/members/{discord_user_id}",
        headers={"Authorization": f"Bot {bot_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        if resp.status_code == 429:
            retry_after = DISPLAY_NAME_ERROR_TTL_SECONDS
            try:
                retry_after = float(resp.json().get("retry_after", retry_after))
            except Exception:
                pass
            _set_rate_limit_cooldown(discord_user_id, retry_after)
            _set_cached_display_name(
                discord_user_id,
                cached_name,
                ttl_seconds=max(retry_after, 1),
            )
        elif resp.status_code == 404:
            _set_cached_display_name(
                discord_user_id,
                cached_name,
                ttl_seconds=DISPLAY_NAME_ERROR_TTL_SECONDS,
            )
        if resp.status_code != 404:
            logger.error("fetch_guild_member_display_name failed: %d %s", resp.status_code, resp.text)
        return cached_name

    member = resp.json()
    user = member.get("user") or {}
    display_name = member.get("nick") or user.get("global_name") or user.get("username")

    if user.get("id") and display_name:
        avatar_url = _discord_asset_url(user["id"], user.get("avatar"), "avatars")
        banner_url = _discord_asset_url(user["id"], user.get("banner"), "banners")
        upsert_user(
            user["id"],
            display_name,
            avatar_url,
            discord_banner=banner_url,
            accent_color=user.get("accent_color"),
            locale=user.get("locale"),
            discord_bio=user.get("bio"),
        )
        _set_cached_display_name(discord_user_id, display_name)

    return display_name or cached_name


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
        avatar_url = _discord_asset_url(discord_id, discord_user.get("avatar"), "avatars")
        banner_url = _discord_asset_url(discord_id, discord_user.get("banner"), "banners")

        upsert_user(
            discord_id,
            username,
            avatar_url,
            discord_banner=banner_url,
            accent_color=discord_user.get("accent_color"),
            locale=discord_user.get("locale"),
            discord_bio=discord_user.get("bio"),
        )

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
