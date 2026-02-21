"""FastAPI app factory with lifespan management."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Database
from .auth import ApiAuth
from .logger import setup_logging
from .session import SessionManager
from ..plugin.manager import PluginManager
from ..transport import mcp as mcp_transport
from ..admin import auth as admin_auth
from ..admin.routes import router as admin_router, user_router, init_admin

logger = logging.getLogger("cortivium")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    setup_logging(settings.log_level)
    settings.ensure_secret_key()

    # Database
    db_path = str(settings.resolve_path(settings.database_path))
    db = Database(db_path)
    await db.connect()

    # Migrations
    migrations_dir = str(Path(__file__).parent.parent.parent / "migrations")
    await db.run_migrations(migrations_dir)

    # Auth
    api_auth = ApiAuth(db)

    # Sessions
    sessions = SessionManager()

    # Plugin manager
    plugins = PluginManager()

    # Load Ghost OOTM plugin
    from ..plugins.ghost_ootm.plugin import Plugin as GhostPlugin

    ghost = GhostPlugin()
    await plugins.register_plugin(ghost, {}, db)

    # Register plugin in DB if not exists, and sync tool count
    ghost_tools = await ghost.get_tools()
    existing = await db.query_one(
        "SELECT id FROM plugins WHERE name = ?", ("ghost-ootm",)
    )
    if not existing:
        await db.insert(
            "plugins",
            {
                "name": "ghost-ootm",
                "display_name": "Ghost OOTM",
                "description": "Create and manage ghost skills — portable MCP tools tied to your API key",
                "version": "1.0.0",
                "is_enabled": 1,
                "is_public": 0,
            },
        )
    await db.execute(
        "UPDATE plugins SET tool_count = ? WHERE name = ?",
        (len(ghost_tools), "ghost-ootm"),
    )

    # Wire up MCP transport
    mcp_transport.set_dependencies(sessions, plugins, api_auth)

    # Wire up admin panel
    admin_auth.init_auth(settings.secret_key, db)
    init_admin(db)

    # First-run bootstrap
    await _first_run_bootstrap(db)

    # Session cleanup task
    async def cleanup_loop():
        while True:
            await asyncio.sleep(60)
            removed = sessions.cleanup()
            if removed:
                logger.debug(f"Cleaned up {removed} expired sessions")

    cleanup_task = asyncio.create_task(cleanup_loop())

    plugin_count = len(plugins.get_plugin_names())
    tool_count = len(await plugins.get_all_tools())
    logger.info(
        f"Cortivium started — {plugin_count} plugins, {tool_count} tools"
    )

    yield

    # Shutdown
    cleanup_task.cancel()
    await plugins.shutdown()
    await db.close()
    logger.info("Cortivium shut down")


async def _first_run_bootstrap(db: Database) -> None:
    """Create admin user on first run if users table is empty."""
    count = await db.query_value("SELECT COUNT(*) FROM users")
    if count and count > 0:
        return

    password = secrets.token_urlsafe(12)
    from ..admin.auth import hash_password

    await db.insert(
        "users",
        {
            "username": "admin",
            "email": "admin@localhost",
            "password_hash": hash_password(password),
            "name": "Administrator",
            "access_level": 3,
        },
    )

    print("\n" + "=" * 60)
    print("  FIRST RUN — Admin credentials")
    print(f"  Username: admin")
    print(f"  Password: {password}")
    print("  Change this password after first login!")
    print("=" * 60 + "\n")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Cortivium MCP Server",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Mcp-Session-Id", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )

    # MCP routes at root
    app.include_router(mcp_transport.router)

    # Admin panel + user panel
    app.include_router(admin_router)
    app.include_router(user_router)

    # Static files
    static_dir = Path(__file__).parent.parent / "admin" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
