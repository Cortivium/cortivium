"""MCP Protocol handler — JSON-RPC 2.0 message utilities."""

from __future__ import annotations

import json
from typing import Any


VERSION = "2024-11-05"

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ProtocolError(Exception):
    def __init__(self, message: str, code: int = INTERNAL_ERROR):
        super().__init__(message)
        self.code = code


def parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Parse error", PARSE_ERROR) from exc


def success(request_id: int | str | None, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def notification(method: str, params: dict | None = None) -> dict:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params:
        msg["params"] = params
    return msg


def progress(
    token: str,
    progress_val: int,
    total: int | None = None,
    message: str | None = None,
) -> dict:
    params: dict[str, Any] = {"progressToken": token, "progress": progress_val}
    if total is not None:
        params["total"] = total
    if message is not None:
        params["message"] = message
    return notification("notifications/progress", params)


def is_notification(msg: dict) -> bool:
    return "id" not in msg


def is_response(msg: dict) -> bool:
    return "result" in msg or "error" in msg


def is_request(msg: dict) -> bool:
    return "id" in msg and "method" in msg
