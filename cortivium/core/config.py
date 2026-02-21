"""Configuration via pydantic-settings, reading from .env file."""

import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    server_name: str = "cortivium"
    server_version: str = "1.0.0"

    # Security
    secret_key: str = ""

    # Database
    database_path: str = "storage/cortivium.db"

    # Storage
    storage_path: str = "storage"

    # Logging
    log_level: str = "info"

    # SSL
    ssl_cert: str = ""
    ssl_key: str = ""

    model_config = {
        "env_prefix": "CORTIVIUM_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    def ensure_secret_key(self) -> None:
        """Auto-generate secret key if not set, and persist to .env."""
        if self.secret_key:
            return
        self.secret_key = secrets.token_hex(32)
        env_path = Path(".env")
        line = f"CORTIVIUM_SECRET_KEY={self.secret_key}\n"
        if env_path.exists():
            content = env_path.read_text()
            if "CORTIVIUM_SECRET_KEY=" not in content:
                with open(env_path, "a") as f:
                    f.write(line)
        else:
            env_path.write_text(line)

    def resolve_path(self, path: str) -> Path:
        """Resolve a path relative to the project root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(os.getcwd()) / p


settings = Settings()
