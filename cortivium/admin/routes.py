"""Admin panel routes — all pages served via Jinja2 templates."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Form, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth
from ..core.database import Database

logger = logging.getLogger("cortivium.admin")

router = APIRouter(prefix="/admin")
user_router = APIRouter(prefix="/user")

_db: Database | None = None
_templates: Jinja2Templates | None = None


def init_admin(db: Database) -> None:
    global _db, _templates
    _db = db
    template_dir = Path(__file__).parent / "templates"
    _templates = Jinja2Templates(directory=str(template_dir))

    # Template globals
    _templates.env.globals["access_level_name"] = auth.access_level_name
    _templates.env.globals["format_number"] = _format_number
    _templates.env.globals["time_ago"] = _time_ago
    _templates.env.globals["cache_v"] = str(int(time.time()))
    _templates.env.globals["billing_enabled"] = False


def _format_number(num: int | float) -> str:
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1000:
        return f"{num / 1000:.1f}K"
    return f"{num:,}"


def _time_ago(dt_str: str | None) -> str:
    if not dt_str:
        return "Never"
    if not isinstance(dt_str, str):
        return str(dt_str)
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return dt_str
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (now - dt).total_seconds()
    if diff < 60:
        return "Just now"
    if diff < 3600:
        mins = int(diff / 60)
        return f"{mins} min{'s' if mins > 1 else ''} ago"
    if diff < 86400:
        hours = int(diff / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    if diff < 604800:
        days = int(diff / 86400)
        return f"{days} day{'s' if days > 1 else ''} ago"
    return dt.strftime("%b %d, %Y")


def _base_path(request: Request) -> str:
    """Return '/admin' or '/user' based on current request path."""
    return "/user" if request.url.path.startswith("/user") else "/admin"


def _redirect_msg(bp: str, page: str, msg: str, mt: str = "success") -> RedirectResponse:
    """Build a redirect with URL-encoded message query params."""
    return RedirectResponse(
        f"{bp}/{page}?msg={urlquote(msg)}&mt={mt}", status_code=302
    )


def _check_auth(request: Request, min_level: int | None = None):
    """Returns (user, response) — if response is set, return it immediately.

    If min_level is None, auto-detects from path: /admin/ requires ACCESS_ADMIN,
    /user/ requires ACCESS_USER.
    """
    bp = _base_path(request)
    if min_level is None:
        min_level = auth.ACCESS_ADMIN if bp == "/admin" else auth.ACCESS_USER
    user = auth.get_current_user(request)
    if not user:
        return None, RedirectResponse(f"{bp}/login", status_code=302)
    if user.get("access_level", 0) < min_level:
        return None, _render(
            request,
            "denied.html",
            user,
            page_title="Access Denied",
        )
    return user, None


def _render(
    request: Request,
    template: str,
    user: dict,
    **ctx,
) -> HTMLResponse:
    csrf = request.cookies.get("cortivium_csrf", "")
    if not csrf:
        csrf = auth.generate_csrf()
    bp = _base_path(request)
    is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN if user else False
    resp = _templates.TemplateResponse(
        template,
        {"request": request, "user": user, "csrf_token": csrf, "bp": bp, "is_admin": is_admin, **ctx},
    )
    if not request.cookies.get("cortivium_csrf"):
        resp.set_cookie("cortivium_csrf", csrf, httponly=True, samesite="strict")
    return resp


# =========================================================================
# Login / Logout
# =========================================================================


def _login_redirect(user_data: dict) -> str:
    """Return the correct home URL for a user based on access level."""
    if user_data.get("access_level", 0) >= auth.ACCESS_ADMIN:
        return "/admin/"
    return "/user/"


async def _handle_login_page(request: Request):
    user = auth.get_current_user(request)
    if user:
        return RedirectResponse(_login_redirect(user), status_code=302)
    csrf = auth.generate_csrf()
    resp = _templates.TemplateResponse(
        "login.html", {"request": request, "error": "", "csrf_token": csrf}
    )
    resp.set_cookie("cortivium_csrf", csrf, httponly=True, samesite="strict")
    return resp


async def _handle_login_submit(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")
    csrf_token = form.get("csrf_token", "")

    if not auth.verify_csrf(request, csrf_token):
        csrf = auth.generate_csrf()
        resp = _templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid request. Please try again.", "csrf_token": csrf},
        )
        resp.set_cookie("cortivium_csrf", csrf, httponly=True, samesite="strict")
        return resp

    if not username or not password:
        csrf = auth.generate_csrf()
        resp = _templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Please enter both username and password.", "csrf_token": csrf},
        )
        resp.set_cookie("cortivium_csrf", csrf, httponly=True, samesite="strict")
        return resp

    result = await auth.authenticate(username, password)
    if isinstance(result, str):
        csrf = auth.generate_csrf()
        resp = _templates.TemplateResponse(
            "login.html", {"request": request, "error": result, "csrf_token": csrf}
        )
        resp.set_cookie("cortivium_csrf", csrf, httponly=True, samesite="strict")
        return resp

    resp = RedirectResponse(_login_redirect(result), status_code=302)
    auth.set_session(resp, result)
    return resp


async def _handle_logout(request: Request):
    bp = _base_path(request)
    resp = RedirectResponse(f"{bp}/login", status_code=302)
    auth.clear_session(resp)
    return resp


@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return await _handle_login_page(request)


@router.post("/login", response_class=HTMLResponse)
async def admin_login_submit(request: Request):
    return await _handle_login_submit(request)


@router.get("/logout")
async def admin_logout(request: Request):
    return await _handle_logout(request)


@user_router.get("/login", response_class=HTMLResponse)
async def user_login_page(request: Request):
    return await _handle_login_page(request)


@user_router.post("/login", response_class=HTMLResponse)
async def user_login_submit(request: Request):
    return await _handle_login_submit(request)


@user_router.get("/logout")
async def user_logout(request: Request):
    return await _handle_logout(request)


# =========================================================================
# Dashboard
# =========================================================================


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user, deny = _check_auth(request)
    if deny:
        return deny

    is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN
    user_email = user.get("email", "")

    if is_admin:
        key_filter = ""
        log_filter = ""
        key_params: list = []
        log_params: list = []
    else:
        key_filter = " WHERE owner_email = ?"
        log_filter = " AND ak.owner_email = ?"
        key_params = [user_email]
        log_params = [user_email]

    stats = {
        "total_keys": await _db.query_value(
            f"SELECT COUNT(*) FROM api_keys{key_filter}", key_params
        ) or 0,
        "active_keys": await _db.query_value(
            f"SELECT COUNT(*) FROM api_keys WHERE is_active = 1{' AND owner_email = ?' if not is_admin else ''}",
            log_params if not is_admin else [],
        ) or 0,
        "total_requests": await _db.query_value(
            f"SELECT COALESCE(SUM(total_requests), 0) FROM api_keys{key_filter}", key_params
        ) or 0,
        "requests_today": await _db.query_value(
            "SELECT COUNT(*) FROM usage_logs ul JOIN api_keys ak ON ul.api_key_id = ak.id "
            f"WHERE DATE(ul.request_timestamp) = DATE('now'){log_filter}",
            log_params,
        ) or 0,
        "requests_this_hour": await _db.query_value(
            "SELECT COUNT(*) FROM usage_logs ul JOIN api_keys ak ON ul.api_key_id = ak.id "
            f"WHERE ul.request_timestamp >= datetime('now', '-1 hour'){log_filter}",
            log_params,
        ) or 0,
    }
    if is_admin:
        stats["plugins_enabled"] = await _db.query_value(
            "SELECT COUNT(*) FROM plugins WHERE is_enabled = 1"
        ) or 0

    recent_activity = await _db.query(
        "SELECT ul.*, ak.name as key_name, ak.key_prefix "
        "FROM usage_logs ul "
        "JOIN api_keys ak ON ul.api_key_id = ak.id "
        f"WHERE 1=1{log_filter} "
        "ORDER BY ul.request_timestamp DESC LIMIT 20",
        log_params,
    )

    top_tools = await _db.query(
        "SELECT tool_name, plugin_name, COUNT(*) as calls, "
        "AVG(duration_ms) as avg_duration, "
        "SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successes "
        "FROM usage_logs ul JOIN api_keys ak ON ul.api_key_id = ak.id "
        f"WHERE ul.request_timestamp >= datetime('now', '-7 days'){log_filter} "
        "GROUP BY tool_name, plugin_name "
        "ORDER BY calls DESC LIMIT 10",
        log_params,
    )

    return _render(
        request,
        "dashboard.html",
        user,
        page_title="Dashboard",
        stats=stats,
        recent_activity=recent_activity,
        top_tools=top_tools,
    )


# =========================================================================
# API Keys
# =========================================================================


@router.get("/keys", response_class=HTMLResponse)
async def keys_page(request: Request):
    user, deny = _check_auth(request)
    if deny:
        return deny

    is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN
    if is_admin:
        keys = await _db.query(
            "SELECT id, key_prefix, name, description, owner_email, is_active, "
            "rate_limit_per_minute, total_requests, last_used_at, created_at, expires_at "
            "FROM api_keys ORDER BY created_at DESC"
        )
    else:
        keys = await _db.query(
            "SELECT id, key_prefix, name, description, owner_email, is_active, "
            "rate_limit_per_minute, total_requests, last_used_at, created_at, expires_at "
            "FROM api_keys WHERE owner_email = ? ORDER BY created_at DESC",
            (user.get("email", ""),),
        )
    message = request.query_params.get("msg", "")
    msg_type = request.query_params.get("mt", "")

    return _render(
        request,
        "keys.html",
        user,
        page_title="API Keys",
        keys=keys,
        message=message,
        message_type=msg_type,
    )


@router.post("/keys", response_class=HTMLResponse)
async def keys_action(request: Request):
    user, deny = _check_auth(request)
    if deny:
        return deny

    form = await request.form()
    action = form.get("action", "")
    csrf_token = form.get("csrf_token", "")
    name = form.get("name", "")
    email = form.get("email", "")
    description = form.get("description", "")
    id = int(form.get("id", 0) or 0)
    active = int(form.get("active", 0) or 0)

    bp = _base_path(request)
    if not auth.verify_csrf(request, csrf_token):
        return _redirect_msg(bp, "keys", "Invalid request", "error")

    is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN
    user_email = user.get("email", "")
    # Non-admins can only act on their own keys
    own_filter = "" if is_admin else " AND owner_email = ?"
    own_params = [] if is_admin else [user_email]

    msg = ""
    mt = "success"

    if action == "create" and name:
        # Non-admins always own the key; admins can set any owner
        owner = email.strip() if (is_admin and email.strip()) else user_email

        raw_key = secrets.token_hex(24)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]
        await _db.insert(
            "api_keys",
            {
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "name": name.strip(),
                "description": description.strip() or None,
                "owner_email": owner,
            },
        )
        msg = f"API Key created: {raw_key} — save it now, it won't be shown again!"
    elif action == "toggle":
        await _db.execute(
            f"UPDATE api_keys SET is_active = ? WHERE id = ?{own_filter}",
            [active, id] + own_params,
        )
        msg = "Key status updated"
    elif action == "update" and id:
        updates = {}
        if name.strip():
            updates["name"] = name.strip()
        if is_admin and email.strip():
            updates["owner_email"] = email.strip()
        updates["description"] = description.strip() or None
        if updates:
            await _db.update("api_keys", updates, f"id = ?{own_filter}", [id] + own_params)
            msg = "Key updated"
        else:
            msg = "Nothing to update"
            mt = "warning"
    elif action == "delete":
        await _db.execute(
            f"DELETE FROM api_keys WHERE id = ?{own_filter}",
            [id] + own_params,
        )
        msg = "Key deleted"
    else:
        msg = "Name is required"
        mt = "error"
    return _redirect_msg(bp, "keys", msg, mt)


# =========================================================================
# Ghost Skills
# =========================================================================


@router.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request):
    user, deny = _check_auth(request)
    if deny:
        return deny

    user_email = user.get("email", "")
    is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN

    if is_admin:
        user_api_keys = await _db.query(
            "SELECT id, name, key_prefix FROM api_keys WHERE is_active = 1 ORDER BY name",
        )
    else:
        user_api_keys = await _db.query(
            "SELECT id, name, key_prefix FROM api_keys WHERE owner_email = ? AND is_active = 1 ORDER BY name",
            (user_email,),
        )

    selected_key = int(request.query_params.get("api_key", "0") or 0)
    message = request.query_params.get("msg", "")
    msg_type = request.query_params.get("mt", "")

    if is_admin:
        sql = (
            "SELECT gs.*, ak.name as api_key_name, ak.key_prefix "
            "FROM ghost_scripts gs "
            "JOIN api_keys ak ON gs.api_key_id = ak.id "
            "WHERE 1=1"
        )
        params: list = []
    else:
        sql = (
            "SELECT gs.*, ak.name as api_key_name, ak.key_prefix "
            "FROM ghost_scripts gs "
            "JOIN api_keys ak ON gs.api_key_id = ak.id "
            "WHERE ak.owner_email = ?"
        )
        params: list = [user_email]
    if selected_key:
        sql += " AND gs.api_key_id = ?"
        params.append(selected_key)
    sql += " ORDER BY gs.name ASC"

    skills = await _db.query(sql, params)

    return _render(
        request,
        "skills.html",
        user,
        page_title="Ghost Skills",
        skills=skills,
        user_api_keys=user_api_keys,
        selected_key=selected_key,
        message=message,
        message_type=msg_type,
    )


@router.post("/skills", response_class=HTMLResponse)
async def skills_action(request: Request):
    user, deny = _check_auth(request)
    if deny:
        return deny

    form = await request.form()
    action = form.get("action", "")
    csrf = form.get("csrf_token", "")

    bp = _base_path(request)
    if not auth.verify_csrf(request, csrf):
        return _redirect_msg(bp, "skills", "Invalid request", "error")

    msg = ""
    mt = "success"
    user_email = user.get("email", "")

    if action == "create":
        api_key_id = int(form.get("api_key_id", 0))
        name = (form.get("name") or "").strip()
        desc = (form.get("description") or "").strip()
        instructions = (form.get("instructions") or "").strip()
        trigger_str = (form.get("trigger_phrases") or "").strip()
        trigger_phrases = [t.strip() for t in trigger_str.split(",") if t.strip()]

        if not name or not desc or not instructions:
            msg, mt = "Name, description, and instructions are required.", "error"
        elif not re.match(r"^[a-z][a-z0-9_]*$", name):
            msg, mt = "Invalid name format.", "error"
        else:
            existing = await _db.query_one(
                "SELECT id FROM ghost_scripts WHERE api_key_id = ? AND name = ?",
                (api_key_id, name),
            )
            if existing:
                msg, mt = f"Name '{name}' already exists.", "error"
            else:
                await _db.insert(
                    "ghost_scripts",
                    {
                        "api_key_id": api_key_id,
                        "name": name,
                        "display_name": name,
                        "description": desc,
                        "type": "skill",
                        "instructions": instructions,
                        "trigger_phrases": json.dumps(trigger_phrases),
                    },
                )
                msg = f"Ghost skill 'ghost_{name}' created!"

    elif action == "update":
        skill_id = int(form.get("id", 0))
        desc = (form.get("description") or "").strip()
        instructions = (form.get("instructions") or "").strip()
        trigger_str = (form.get("trigger_phrases") or "").strip()
        trigger_phrases = [t.strip() for t in trigger_str.split(",") if t.strip()]
        is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN

        if is_admin:
            skill = await _db.query_one(
                "SELECT gs.* FROM ghost_scripts gs WHERE gs.id = ?", (skill_id,)
            )
        else:
            skill = await _db.query_one(
                "SELECT gs.* FROM ghost_scripts gs JOIN api_keys ak ON gs.api_key_id = ak.id "
                "WHERE gs.id = ? AND ak.owner_email = ?",
                (skill_id, user_email),
            )
        if not skill:
            msg, mt = "Skill not found or access denied.", "error"
        else:
            update_data: dict = {
                "description": desc,
                "trigger_phrases": json.dumps(trigger_phrases),
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }
            if skill["type"] == "skill":
                update_data["instructions"] = instructions
            await _db.update("ghost_scripts", update_data, "id = ?", [skill_id])
            msg = "Skill updated!"

    elif action == "toggle":
        skill_id = int(form.get("id", 0))
        enabled = int(form.get("is_enabled", 0))
        is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN

        if is_admin:
            skill = await _db.query_one(
                "SELECT gs.id FROM ghost_scripts gs WHERE gs.id = ?", (skill_id,)
            )
        else:
            skill = await _db.query_one(
                "SELECT gs.id FROM ghost_scripts gs JOIN api_keys ak ON gs.api_key_id = ak.id "
                "WHERE gs.id = ? AND ak.owner_email = ?",
                (skill_id, user_email),
            )
        if skill:
            await _db.update("ghost_scripts", {"is_enabled": enabled}, "id = ?", [skill_id])
            msg = "Skill enabled." if enabled else "Skill disabled."

    elif action == "delete":
        skill_id = int(form.get("id", 0))
        is_admin = user.get("access_level", 0) >= auth.ACCESS_ADMIN

        if is_admin:
            skill = await _db.query_one(
                "SELECT gs.name FROM ghost_scripts gs WHERE gs.id = ?", (skill_id,)
            )
        else:
            skill = await _db.query_one(
                "SELECT gs.name FROM ghost_scripts gs JOIN api_keys ak ON gs.api_key_id = ak.id "
                "WHERE gs.id = ? AND ak.owner_email = ?",
                (skill_id, user_email),
            )
        if skill:
            await _db.execute("DELETE FROM ghost_scripts WHERE id = ?", (skill_id,))
            msg = f"Skill 'ghost_{skill['name']}' deleted."
        else:
            msg, mt = "Skill not found.", "error"

    return _redirect_msg(bp, "skills", msg, mt)


# =========================================================================
# Plugins
# =========================================================================


@router.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request):
    user, deny = _check_auth(request, auth.ACCESS_ADMIN)
    if deny:
        return deny

    plugins = await _db.query(
        "SELECT * FROM plugins ORDER BY name"
    )
    message = request.query_params.get("msg", "")
    msg_type = request.query_params.get("mt", "")

    return _render(
        request,
        "plugins.html",
        user,
        page_title="Plugins",
        plugins=plugins,
        message=message,
        message_type=msg_type,
    )


@router.post("/plugins", response_class=HTMLResponse)
async def plugins_action(request: Request):
    user, deny = _check_auth(request, auth.ACCESS_ADMIN)
    if deny:
        return deny

    form = await request.form()
    action = form.get("action", "")
    csrf_token = form.get("csrf_token", "")
    id = int(form.get("id", 0) or 0)
    enabled = int(form.get("enabled", 0) or 0)

    bp = _base_path(request)
    if not auth.verify_csrf(request, csrf_token):
        return _redirect_msg(bp, "plugins", "Invalid request", "error")

    if action == "toggle":
        await _db.update("plugins", {"is_enabled": enabled}, "id = ?", [id])

    return _redirect_msg(bp, "plugins", "Updated")


# =========================================================================
# Usage Logs
# =========================================================================


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    user, deny = _check_auth(request, auth.ACCESS_ADMIN)
    if deny:
        return deny

    page = max(1, int(request.query_params.get("page", "1") or 1))
    per_page = 50
    offset = (page - 1) * per_page

    filter_key = request.query_params.get("key", "")
    filter_tool = request.query_params.get("tool", "")
    filter_status = request.query_params.get("status", "")

    where_parts = []
    params: list = []

    if filter_key:
        where_parts.append("ak.key_prefix LIKE ?")
        params.append(f"{filter_key}%")
    if filter_tool:
        where_parts.append("ul.tool_name = ?")
        params.append(filter_tool)
    if filter_status:
        where_parts.append("ul.status = ?")
        params.append(filter_status)

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = (
        await _db.query_value(
            f"SELECT COUNT(*) FROM usage_logs ul JOIN api_keys ak ON ul.api_key_id = ak.id {where_clause}",
            params,
        )
        or 0
    )
    total_pages = max(1, math.ceil(total / per_page))

    logs = await _db.query(
        f"SELECT ul.*, ak.name as key_name, ak.key_prefix "
        f"FROM usage_logs ul JOIN api_keys ak ON ul.api_key_id = ak.id "
        f"{where_clause} ORDER BY ul.request_timestamp DESC LIMIT {per_page} OFFSET {offset}",
        params,
    )

    tools = await _db.query(
        "SELECT DISTINCT tool_name FROM usage_logs ORDER BY tool_name"
    )

    return _render(
        request,
        "logs.html",
        user,
        page_title="Usage Logs",
        logs=logs,
        tools=tools,
        total=total,
        page=page,
        total_pages=total_pages,
        filter_key=filter_key,
        filter_tool=filter_tool,
        filter_status=filter_status,
    )


# =========================================================================
# Users
# =========================================================================


@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    user, deny = _check_auth(request, auth.ACCESS_ADMIN)
    if deny:
        return deny

    users = await _db.query(
        "SELECT id, username, email, name, access_level, tier, created_at, last_login "
        "FROM users ORDER BY id"
    )
    message = request.query_params.get("msg", "")
    msg_type = request.query_params.get("mt", "")

    return _render(
        request,
        "users.html",
        user,
        page_title="Users",
        users=users,
        message=message,
        message_type=msg_type,
    )


@router.post("/users", response_class=HTMLResponse)
async def users_action(request: Request):
    user, deny = _check_auth(request, auth.ACCESS_ADMIN)
    if deny:
        return deny

    form = await request.form()
    action = form.get("action", "")
    csrf = form.get("csrf_token", "")

    bp = _base_path(request)
    if not auth.verify_csrf(request, csrf):
        return _redirect_msg(bp, "users", "Invalid request", "error")

    msg = ""
    mt = "success"

    if action == "create":
        username = (form.get("username") or "").strip()
        email = (form.get("email") or "").strip()
        password = form.get("password", "")
        name = (form.get("name") or "").strip()
        access_level = int(form.get("access_level", auth.ACCESS_PENDING))

        if not username or not email or not password:
            msg, mt = "All fields are required.", "error"
        elif len(password) < 8:
            msg, mt = "Password must be at least 8 characters.", "error"
        else:
            existing = await _db.query_one(
                "SELECT id FROM users WHERE username = ? OR email = ?",
                (username, email),
            )
            if existing:
                msg, mt = "Username or email already exists.", "error"
            else:
                await _db.insert(
                    "users",
                    {
                        "username": username,
                        "email": email,
                        "password_hash": auth.hash_password(password),
                        "name": name,
                        "access_level": access_level,
                    },
                )
                msg = "User created."

    elif action == "update":
        user_id = int(form.get("user_id", 0))
        username = (form.get("username") or "").strip()
        email = (form.get("email") or "").strip()
        name = (form.get("name") or "").strip()
        if not username or not email:
            msg, mt = "Username and email are required.", "error"
        else:
            dup = await _db.query_one(
                "SELECT id FROM users WHERE (username = ? OR email = ?) AND id != ?",
                (username, email, user_id),
            )
            if dup:
                msg, mt = "Username or email already exists.", "error"
            else:
                await _db.update(
                    "users",
                    {"username": username, "email": email, "name": name or None},
                    "id = ?",
                    [user_id],
                )
                msg = "User updated."

    elif action == "update_level":
        user_id = int(form.get("user_id", 0))
        level = int(form.get("access_level", 0))
        if user_id == user["user_id"]:
            msg, mt = "Cannot change your own access level.", "error"
        else:
            await _db.update("users", {"access_level": level}, "id = ?", [user_id])
            msg = "Access level updated."

    elif action == "reset_password":
        user_id = int(form.get("user_id", 0))
        new_password = form.get("new_password", "")
        if len(new_password) < 8:
            msg, mt = "Password must be at least 8 characters.", "error"
        else:
            await _db.update(
                "users",
                {"password_hash": auth.hash_password(new_password)},
                "id = ?",
                [user_id],
            )
            msg = "Password updated."

    elif action == "delete":
        user_id = int(form.get("user_id", 0))
        if user_id == user["user_id"]:
            msg, mt = "Cannot delete yourself.", "error"
        else:
            await _db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            msg = "User deleted."

    return _redirect_msg(bp, "users", msg, mt)


# =========================================================================
# User-facing routes (mirrors of user-accessible admin pages under /user/)
# =========================================================================

@user_router.get("/", response_class=HTMLResponse)
async def user_dashboard(request: Request):
    return await dashboard(request)

@user_router.get("/keys", response_class=HTMLResponse)
async def user_keys_page(request: Request):
    return await keys_page(request)

@user_router.post("/keys", response_class=HTMLResponse)
async def user_keys_action(request: Request):
    return await keys_action(request)

@user_router.get("/skills", response_class=HTMLResponse)
async def user_skills_page(request: Request):
    return await skills_page(request)

@user_router.post("/skills", response_class=HTMLResponse)
async def user_skills_action(request: Request):
    return await skills_action(request)
