"""Abstract plugin base class with helpers."""

from __future__ import annotations

from typing import Any

from .interface import PluginInterface


class AbstractPlugin(PluginInterface):
    def __init__(self) -> None:
        self._config: dict = {}
        self._db: Any = None

    async def initialize(self, config: dict, db: Any) -> None:
        self._config = config
        self._db = db

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    @staticmethod
    def text_content(text: str) -> dict:
        return {"content": [{"type": "text", "text": text}]}

    @staticmethod
    def error_content(message: str) -> dict:
        return {"content": [{"type": "text", "text": message}], "isError": True}

    @staticmethod
    def image_content(base64_data: str, mime_type: str) -> dict:
        return {
            "content": [
                {"type": "image", "data": base64_data, "mimeType": mime_type}
            ]
        }
