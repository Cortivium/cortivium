"""Example plugin template."""

from __future__ import annotations

from typing import Any, Callable

from ...plugin.base import AbstractPlugin


class Plugin(AbstractPlugin):
    def get_name(self) -> str:
        return "example"

    async def get_tools(self, context: dict | None = None) -> list[dict]:
        return [
            {
                "name": "example_hello",
                "description": "A simple hello world tool for testing",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name to greet",
                        }
                    },
                    "required": ["name"],
                },
            }
        ]

    async def execute_tool(
        self,
        name: str,
        arguments: dict,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        arguments.pop("_context", None)
        if name == "example_hello":
            who = arguments.get("name", "World")
            return self.text_content(f"Hello, {who}! This is the example plugin.")
        return self.error_content(f"Unknown tool: {name}")
