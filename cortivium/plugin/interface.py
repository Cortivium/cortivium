"""Plugin interface — ABC that all plugins must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable


class PluginInterface(ABC):
    @abstractmethod
    def get_name(self) -> str: ...

    @abstractmethod
    async def initialize(self, config: dict, db: Any) -> None: ...

    async def get_tools(self, context: dict | None = None) -> list[dict]:
        return []

    def get_resources(self) -> list[dict]:
        return []

    def get_prompts(self) -> list[dict]:
        return []

    async def execute_tool(
        self,
        name: str,
        arguments: dict,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        raise NotImplementedError(f"Unknown tool: {name}")

    async def read_resource(self, uri: str) -> dict:
        raise NotImplementedError(f"Unknown resource: {uri}")

    async def get_prompt(self, name: str, arguments: dict) -> dict:
        raise NotImplementedError(f"Unknown prompt: {name}")

    def can_handle_tool(self, name: str) -> bool:
        return False

    async def shutdown(self) -> None:
        pass
