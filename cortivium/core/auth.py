"""API key authentication and rate limiting — in-memory, no Redis."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from .database import Database

logger = logging.getLogger("cortivium.auth")


class ApiAuth:
    def __init__(self, db: Database):
        self._db = db
        # In-memory cache: key_hash -> (data, expires_at)
        self._cache: dict[str, tuple[dict | None, float]] = {}
        # Rate limit counters: bucket_key -> (count, expires_at)
        self._rate_limits: dict[str, tuple[int, float]] = {}

    async def validate_key(self, raw_key: str) -> dict | None:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # Check cache
        now = time.time()
        if key_hash in self._cache:
            data, expires = self._cache[key_hash]
            if now < expires:
                return data if data and data.get("is_active") else None
            del self._cache[key_hash]

        # Query database
        try:
            key_data = await self._db.query_one(
                "SELECT * FROM api_keys WHERE key_hash = ? AND is_active = 1",
                (key_hash,),
            )
        except Exception as exc:
            logger.error(f"Key validation error: {exc}")
            return None

        if not key_data:
            # Cache negative result for 60s
            self._cache[key_hash] = (None, now + 60)
            return None

        # Check expiration
        if key_data.get("expires_at"):
            try:
                expires = datetime.fromisoformat(str(key_data["expires_at"]))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if expires < datetime.now(timezone.utc):
                    self._cache[key_hash] = (None, now + 60)
                    return None
            except (ValueError, TypeError):
                pass

        # Parse JSON fields
        ap = key_data.get("allowed_plugins")
        key_data["allowed_plugins"] = json.loads(ap) if ap else None

        # Cache for 5 minutes
        self._cache[key_hash] = (key_data, now + 300)
        return key_data

    def check_rate_limit(
        self,
        key_id: int,
        limit_per_minute: int = 2,
        limit_per_hour: int = 100,
        limit_per_day: int = 2400,
    ) -> tuple[bool, int, int, str]:
        """Returns (allowed, remaining, reset_seconds, period)."""
        now = time.time()
        self._cleanup_rate_limits(now)

        checks = [
            (f"key:{key_id}:min", limit_per_minute, 60, "minute"),
            (f"key:{key_id}:hour", limit_per_hour, 3600, "hour"),
            (f"key:{key_id}:day", limit_per_day, 86400, "day"),
        ]

        for bucket, limit, window, period in checks:
            entry = self._rate_limits.get(bucket)
            if entry:
                count, expires = entry
                if now < expires and count >= limit:
                    return (False, 0, int(expires - now), period)

        # Increment all counters
        for bucket, limit, window, period in checks:
            entry = self._rate_limits.get(bucket)
            if entry and now < entry[1]:
                self._rate_limits[bucket] = (entry[0] + 1, entry[1])
            else:
                self._rate_limits[bucket] = (1, now + window)

        min_entry = self._rate_limits.get(f"key:{key_id}:min")
        remaining = max(0, limit_per_minute - (min_entry[0] if min_entry else 0))
        reset = int(min_entry[1] - now) if min_entry else 60

        return (True, remaining, reset, "ok")

    def _cleanup_rate_limits(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._rate_limits.items() if now >= exp]
        for k in expired:
            del self._rate_limits[k]

    def can_access_plugin(self, key_data: dict, plugin_name: str) -> bool:
        ap = key_data.get("allowed_plugins")
        if ap is None:
            return True
        return plugin_name in ap

    async def log_usage(
        self,
        api_key_id: int,
        tool_name: str,
        plugin_name: str,
        method: str,
        status: str,
        duration_ms: int,
        error_message: str | None = None,
        request_size: int | None = None,
        response_size: int | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        session_id: str | None = None,
    ) -> None:
        try:
            await self._db.insert(
                "usage_logs",
                {
                    "api_key_id": api_key_id,
                    "tool_name": tool_name,
                    "plugin_name": plugin_name,
                    "method": method,
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_message": error_message,
                    "request_size_bytes": request_size,
                    "response_size_bytes": response_size,
                    "client_ip": client_ip,
                    "user_agent": user_agent,
                    "session_id": session_id,
                },
            )
            await self._db.execute(
                "UPDATE api_keys SET total_requests = total_requests + 1, last_used_at = datetime('now') WHERE id = ?",
                (api_key_id,),
            )
            await self._db.execute(
                "UPDATE plugins SET total_calls = total_calls + 1 WHERE name = ?",
                (plugin_name,),
            )
            if tool_name and plugin_name:
                await self._db.execute(
                    "UPDATE tools SET total_calls = total_calls + 1 "
                    "WHERE name = ? AND plugin_id = (SELECT id FROM plugins WHERE name = ?)",
                    (tool_name, plugin_name),
                )
        except Exception as exc:
            logger.error(f"Usage logging error: {exc}")

    def invalidate_cache(self, key_hash: str) -> None:
        self._cache.pop(key_hash, None)
