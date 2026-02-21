"""Admin authentication — signed cookies + CSRF."""

from __future__ import annotations

import secrets
from typing import Any

import bcrypt as _bcrypt
from fastapi import Request, Response
from itsdangerous import URLSafeTimedSerializer, BadSignature

ACCESS_DISABLED = 0
ACCESS_PENDING = 1
ACCESS_USER = 2
ACCESS_ADMIN = 3
ACCESS_SUPER_ADMIN = 4

_serializer: URLSafeTimedSerializer | None = None
_db: Any = None

SESSION_MAX_AGE = 86400  # 24 hours


def init_auth(secret_key: str, db: Any) -> None:
    global _serializer, _db
    _serializer = URLSafeTimedSerializer(secret_key)
    _db = db


def _sign(data: dict) -> str:
    return _serializer.dumps(data)


def _unsign(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, Exception):
        return None


def get_current_user(request: Request) -> dict | None:
    cookie = request.cookies.get("cortivium_session")
    if not cookie:
        return None
    data = _unsign(cookie)
    if not data or "user_id" not in data:
        return None
    return data


def set_session(response: Response, user: dict) -> None:
    token = _sign(
        {
            "user_id": user["id"],
            "username": user["username"],
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "access_level": user["access_level"],
        }
    )
    response.set_cookie(
        "cortivium_session",
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie("cortivium_session")


def generate_csrf() -> str:
    return secrets.token_hex(32)


def set_csrf(response: Response) -> str:
    token = generate_csrf()
    response.set_cookie("cortivium_csrf", token, httponly=True, samesite="strict")
    return token


def verify_csrf(request: Request, token: str) -> bool:
    cookie = request.cookies.get("cortivium_csrf", "")
    if not cookie or not token:
        return False
    return secrets.compare_digest(cookie, token)


async def authenticate(username: str, password: str) -> dict | str:
    """Authenticate user. Returns user dict on success, error string on failure."""
    user = await _db.query_one(
        "SELECT id, username, email, password_hash, name, access_level FROM users "
        "WHERE username = ? OR email = ?",
        (username, username),
    )

    if not user:
        return "Invalid username or password."

    if not _bcrypt.checkpw(
        password.encode("utf-8"), user["password_hash"].encode("utf-8")
    ):
        return "Invalid username or password."

    if user["access_level"] == ACCESS_DISABLED:
        return "Your account has been disabled."

    if user["access_level"] == ACCESS_PENDING:
        return "Your account is pending approval."

    await _db.execute(
        "UPDATE users SET last_login = datetime('now') WHERE id = ?",
        (user["id"],),
    )
    return user


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(
        password.encode("utf-8"), _bcrypt.gensalt()
    ).decode("utf-8")


def access_level_name(level: int) -> str:
    return {0: "Disabled", 1: "Pending", 2: "User", 3: "Admin", 4: "Super Admin"}.get(
        level, f"Admin ({level})"
    )
