#!/usr/bin/env python3
"""Cortivium MCP Server — entry point."""

import uvicorn

from cortivium.core.app import create_app
from cortivium.core.config import settings

app = create_app()

if __name__ == "__main__":
    ssl_kwargs = {}
    if settings.ssl_cert and settings.ssl_key:
        ssl_kwargs["ssl_certfile"] = settings.ssl_cert
        ssl_kwargs["ssl_keyfile"] = settings.ssl_key

    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        **ssl_kwargs,
    )
