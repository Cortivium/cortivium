"""Async SQLite database wrapper with migration support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger("cortivium.database")


class Database:
    def __init__(self, db_path: str):
        self._path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected")
        return self._db

    async def query(self, sql: str, params: tuple | list = ()) -> list[dict]:
        async with self.db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            if rows and cursor.description:
                cols = [d[0] for d in cursor.description]
                return [dict(zip(cols, row)) for row in rows]
            return []

    async def query_one(self, sql: str, params: tuple | list = ()) -> dict | None:
        async with self.db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            if row is None or not cursor.description:
                return None
            cols = [d[0] for d in cursor.description]
            return dict(zip(cols, row))

    async def query_value(self, sql: str, params: tuple | list = ()) -> Any:
        async with self.db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def execute(self, sql: str, params: tuple | list = ()) -> int:
        cursor = await self.db.execute(sql, params)
        await self.db.commit()
        return cursor.rowcount

    async def insert(self, table: str, data: dict) -> int:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        cursor = await self.db.execute(sql, list(data.values()))
        await self.db.commit()
        return cursor.lastrowid or 0

    async def update(
        self, table: str, data: dict, where: str, where_params: list | tuple = ()
    ) -> int:
        set_clause = ", ".join(f"{k} = ?" for k in data.keys())
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        cursor = await self.db.execute(
            sql, list(data.values()) + list(where_params)
        )
        await self.db.commit()
        return cursor.rowcount

    async def run_migrations(self, migrations_dir: str) -> None:
        """Run pending SQL migrations from a directory."""
        await self.db.execute(
            """CREATE TABLE IF NOT EXISTS _migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            )"""
        )
        await self.db.commit()

        mdir = Path(migrations_dir)
        if not mdir.exists():
            return

        applied = {
            row["name"]
            for row in await self.query("SELECT name FROM _migrations")
        }

        for sql_file in sorted(mdir.glob("*.sql")):
            if sql_file.name in applied:
                continue
            logger.info(f"Applying migration: {sql_file.name}")
            sql = sql_file.read_text()
            # Execute each statement separately
            for statement in sql.split(";"):
                statement = statement.strip()
                if statement:
                    await self.db.execute(statement)
            await self.db.execute(
                "INSERT INTO _migrations (name) VALUES (?)", (sql_file.name,)
            )
            await self.db.commit()
            logger.info(f"Migration applied: {sql_file.name}")
