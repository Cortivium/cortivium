"""MCP HTTP transport — JSON-RPC routing over FastAPI."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from ..core import protocol
from ..core.auth import ApiAuth
from ..core.session import SessionManager
from ..plugin.manager import PluginManager

logger = logging.getLogger("cortivium.mcp")

router = APIRouter()

# These are set during app startup via set_dependencies()
_sessions: SessionManager | None = None
_plugins: PluginManager | None = None
_auth: ApiAuth | None = None


def set_dependencies(
    sessions: SessionManager,
    plugins: PluginManager,
    auth: ApiAuth,
) -> None:
    global _sessions, _plugins, _auth
    _sessions = sessions
    _plugins = plugins
    _auth = auth


CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key, Accept, Mcp-Session-Id, MCP-Protocol-Version",
    "Access-Control-Expose-Headers": "Mcp-Session-Id, X-RateLimit-Remaining, X-RateLimit-Reset",
}


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip
    return request.client.host if request.client else ""


async def _authenticate(
    request: Request,
) -> tuple[bool, dict | None, str | None]:
    """Validate API key only. Returns (ok, key_data, error_message).

    Rate limiting is handled separately in post_root for tools/call only.
    """
    raw_key = request.headers.get("x-api-key", "")

    # Fall back to Authorization: Bearer <key> (for Codex compatibility)
    if not raw_key:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            raw_key = auth_header[7:]

    if _auth is None:
        return (True, None, None)

    if not raw_key:
        return (False, None, "API key required")

    key_data = await _auth.validate_key(raw_key)
    if key_data is None:
        return (False, None, "Invalid API key")

    return (True, key_data, None)


def _build_context(key_data: dict | None) -> dict:
    ctx: dict = {}
    if key_data:
        ctx["api_key_id"] = key_data["id"]
        ctx["api_key_name"] = key_data.get("name", "")
        ctx["allowed_plugins"] = key_data.get("allowed_plugins")
    return ctx


async def _is_long_running(tool_name: str) -> bool:
    if _plugins is None:
        return False
    for tool in await _plugins.get_all_tools():
        if tool["name"] == tool_name:
            return tool.get("annotations", {}).get("longRunning", False)
    return False


async def _log_usage(
    key_data: dict | None,
    method: str,
    tool_name: str,
    status: str,
    start_time: float,
    request: Request,
    error_message: str | None = None,
    request_size: int | None = None,
    response_size: int | None = None,
) -> None:
    if _auth is None or key_data is None:
        return
    duration_ms = int((time.time() - start_time) * 1000)
    plugin_name = ""
    if tool_name and _plugins:
        for t in await _plugins.get_all_tools():
            if t["name"] == tool_name:
                plugin_name = t.get("_plugin", "")
                break
    try:
        await _auth.log_usage(
            api_key_id=key_data["id"],
            tool_name=tool_name or method,
            plugin_name=plugin_name or "system",
            method=method,
            status=status,
            duration_ms=duration_ms,
            error_message=error_message,
            request_size=request_size,
            response_size=response_size,
            client_ip=_get_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:500],
            session_id=request.headers.get("mcp-session-id", ""),
        )
    except Exception as exc:
        logger.error(f"Failed to log usage: {exc}")


@router.options("/")
async def options_root():
    return Response(status_code=204, headers=CORS_HEADERS)


@router.delete("/")
async def delete_root(request: Request):
    authenticated, key_data, auth_error = await _authenticate(request)
    if not authenticated:
        return JSONResponse(
            status_code=401,
            content=protocol.error(None, -32001, auth_error or "Unauthorized"),
            headers=CORS_HEADERS,
        )

    session_id = request.headers.get("mcp-session-id", "")
    if session_id and _sessions and _sessions.has(session_id):
        _sessions.remove(session_id)
        logger.info(f"Session ended: {session_id}")

    return Response(status_code=202, headers=CORS_HEADERS)


def _rate_headers(rate_info: dict) -> dict:
    """Build rate-limit response headers."""
    h = {}
    if rate_info:
        h["X-RateLimit-Remaining"] = str(rate_info.get("remaining", ""))
        h["X-RateLimit-Reset"] = str(rate_info.get("reset", ""))
    return h


@router.post("/")
async def post_root(request: Request):
    start_time = time.time()
    authenticated, key_data, auth_error = await _authenticate(request)

    if not authenticated:
        return JSONResponse(
            status_code=401,
            content=protocol.error(None, -32001, auth_error or "Unauthorized"),
            headers=CORS_HEADERS,
        )

    body = await request.body()
    request_size = len(body)
    try:
        message = protocol.parse(body.decode())
    except protocol.ProtocolError as exc:
        await _log_usage(key_data, "parse_error", "", "error", start_time, request, str(exc), request_size=request_size)
        return JSONResponse(
            status_code=400,
            content=protocol.error(None, exc.code, str(exc)),
            headers=CORS_HEADERS,
        )

    # Batch requests not supported
    if isinstance(message, list):
        return JSONResponse(
            status_code=400,
            content=protocol.error(None, protocol.INVALID_REQUEST, "Batch requests are not supported"),
            headers=CORS_HEADERS,
        )

    # Notifications -> 202
    if protocol.is_notification(message):
        method = message.get("method", "")
        logger.debug(f"Notification: {method}")
        return Response(status_code=202, headers=CORS_HEADERS)

    # Responses -> 202
    if protocol.is_response(message):
        return Response(status_code=202, headers=CORS_HEADERS)

    # Request handling
    method = message.get("method", "")
    params = message.get("params", {})
    request_id = message.get("id")
    context = _build_context(key_data)
    tool_name = params.get("name", "") if method == "tools/call" else ""
    rate_info: dict = {}

    # Rate limit only tools/call — init, ping, tools/list don't count
    if method == "tools/call" and _auth is not None and key_data:
        rpm = key_data.get("rate_limit_per_minute", 30)
        rph = key_data.get("rate_limit_per_hour", 500)
        rpd = key_data.get("rate_limit_per_day", 5000)
        allowed, remaining, reset, period = _auth.check_rate_limit(
            key_data["id"], rpm, rph, rpd,
        )
        rate_info = {"remaining": remaining, "reset": reset}
        if not allowed:
            # Return friendly MCP tool response instead of HTTP 429
            response = protocol.success(request_id, {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Your API key has hit its rate limit.\n\n"
                            f"Rate limit exceeded ({period}). Retry after {reset} seconds.\n\n"
                            f"To stop seeing this message, disconnect the MCP server in your "
                            f"client settings and reconnect later."
                        ),
                    }
                ],
                "isError": True,
            })
            headers = {**CORS_HEADERS, "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)}
            return JSONResponse(content=response, headers=headers)

    # Long-running tool -> SSE
    if method == "tools/call" and await _is_long_running(tool_name):
        return await _handle_streaming(
            request_id, params, context, key_data, start_time, request
        )

    # Synchronous
    try:
        result = await _handle_request(method, params, context)
        headers = {**CORS_HEADERS, **_rate_headers(rate_info)}
        response_body = protocol.success(request_id, result)

        if method == "initialize" and "_sessionId" in result:
            headers["Mcp-Session-Id"] = result.pop("_sessionId")
            response_body["result"] = result

        resp_json = json.dumps(response_body)
        response_size = len(resp_json)
        await _log_usage(key_data, method, tool_name, "success", start_time, request, request_size=request_size, response_size=response_size)
        return JSONResponse(content=response_body, headers=headers)

    except protocol.ProtocolError as exc:
        err_body = protocol.error(request_id, exc.code, str(exc))
        response_size = len(json.dumps(err_body))
        await _log_usage(key_data, method, tool_name, "error", start_time, request, str(exc), request_size=request_size, response_size=response_size)
        return JSONResponse(content=err_body, headers=CORS_HEADERS)
    except Exception as exc:
        logger.exception(f"Internal error handling {method}")
        err_body = protocol.error(request_id, protocol.INTERNAL_ERROR, str(exc))
        response_size = len(json.dumps(err_body))
        await _log_usage(key_data, method, tool_name, "error", start_time, request, str(exc), request_size=request_size, response_size=response_size)
        return JSONResponse(content=err_body, headers=CORS_HEADERS)


async def _handle_request(
    method: str, params: dict, context: dict
) -> dict:
    if method == "initialize":
        return await _handle_initialize(params)
    elif method == "ping":
        return {"pong": True}
    elif method == "tools/list":
        return {"tools": _strip_internal(await _plugins.get_all_tools(context))}
    elif method == "tools/call":
        return await _handle_tool_call(params, context=context)
    elif method == "resources/list":
        return {"resources": _plugins.get_all_resources()}
    elif method == "resources/read":
        uri = params.get("uri")
        if not uri:
            raise protocol.ProtocolError("Missing resource URI", protocol.INVALID_PARAMS)
        return await _plugins.read_resource(uri)
    elif method == "prompts/list":
        return {"prompts": _plugins.get_all_prompts()}
    elif method == "prompts/get":
        name = params.get("name")
        if not name:
            raise protocol.ProtocolError("Missing prompt name", protocol.INVALID_PARAMS)
        return await _plugins.get_prompt(name, params.get("arguments", {}))
    else:
        raise protocol.ProtocolError(
            f"Method not found: {method}", protocol.METHOD_NOT_FOUND
        )


def _strip_internal(tools: list[dict]) -> list[dict]:
    """Remove internal _plugin key from tools list before sending to client."""
    return [{k: v for k, v in t.items() if not k.startswith("_")} for t in tools]


async def _handle_initialize(params: dict) -> dict:
    client_version = params.get("protocolVersion", protocol.VERSION)
    client_caps = params.get("capabilities", {})
    client_info = params.get("clientInfo", {})

    session = _sessions.create()
    session.protocol_version = client_version
    session.client_capabilities = client_caps
    session.client_info = client_info

    logger.info(f"Session created: {session.id} {client_info}")

    capabilities: dict = {}
    if _plugins.has_tools():
        capabilities["tools"] = {"listChanged": True}
    if _plugins.has_resources():
        capabilities["resources"] = {"subscribe": False, "listChanged": True}
    if _plugins.has_prompts():
        capabilities["prompts"] = {"listChanged": True}

    return {
        "_sessionId": session.id,
        "protocolVersion": client_version,
        "capabilities": capabilities or {},
        "serverInfo": {
            "name": "cortivium",
            "version": "1.0.0",
        },
    }


async def _handle_tool_call(
    params: dict,
    on_progress=None,
    context: dict | None = None,
) -> dict:
    name = params.get("name")
    if not name:
        raise protocol.ProtocolError("Missing tool name", protocol.INVALID_PARAMS)
    arguments = params.get("arguments", {})
    return await _plugins.execute_tool(name, arguments, on_progress, context)


async def _handle_streaming(
    request_id, params, context, key_data, start_time, request
):
    progress_token = str(
        params.get("_meta", {}).get("progressToken", f"auto-{secrets.token_hex(8)}")
    )
    tool_name = params.get("name", "")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        def on_progress(prog: int, total: int, msg: str):
            notif = protocol.progress(progress_token, prog, total, msg)
            queue.put_nowait(notif)

        async def run_tool():
            try:
                result = await _handle_tool_call(params, on_progress, context)
                await queue.put(("result", result))
            except Exception as exc:
                await queue.put(("error", exc))

        task = asyncio.create_task(run_tool())

        while True:
            item = await queue.get()
            if isinstance(item, tuple):
                kind, payload = item
                if kind == "result":
                    resp = protocol.success(request_id, payload)
                    yield f"data: {json.dumps(resp)}\n\n"
                    await _log_usage(key_data, "tools/call", tool_name, "success", start_time, request)
                else:
                    code = getattr(payload, "code", protocol.INTERNAL_ERROR)
                    resp = protocol.error(request_id, code, str(payload))
                    yield f"data: {json.dumps(resp)}\n\n"
                    await _log_usage(key_data, "tools/call", tool_name, "error", start_time, request, str(payload))
                break
            else:
                yield f"data: {json.dumps(item)}\n\n"

        await task

    headers = dict(CORS_HEADERS)
    headers["Cache-Control"] = "no-cache"
    headers["X-Accel-Buffering"] = "no"
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers=headers,
    )
