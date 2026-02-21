"""Plugin manager — loads, indexes, and routes to plugins."""

from __future__ import annotations

import importlib
import logging
from typing import Any, Callable

from . import interface as iface
from ..core import protocol

logger = logging.getLogger("cortivium.plugins")


class PluginManager:
    def __init__(self) -> None:
        self._plugins: dict[str, iface.PluginInterface] = {}
        self._tool_map: dict[str, str] = {}
        self._resource_map: dict[str, str] = {}
        self._prompt_map: dict[str, str] = {}

    async def load_plugin(
        self, import_path: str, config: dict, db: Any
    ) -> None:
        """Load a plugin by its Python import path (e.g. cortivium.plugins.ghost_ootm.plugin.Plugin)."""
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            plugin = cls()
        except Exception as exc:
            logger.error(f"Failed to load plugin {import_path}: {exc}")
            return

        await self.register_plugin(plugin, config, db)

    async def register_plugin(
        self, plugin: iface.PluginInterface, config: dict, db: Any
    ) -> None:
        name = plugin.get_name()
        if name in self._plugins:
            logger.warning(f"Replacing plugin: {name}")
            await self.unregister_plugin(name)

        await plugin.initialize(config, db)
        self._plugins[name] = plugin

        for tool in await plugin.get_tools():
            self._tool_map[tool["name"]] = name

        for resource in plugin.get_resources():
            self._resource_map[resource["uri"]] = name

        for prompt in plugin.get_prompts():
            self._prompt_map[prompt["name"]] = name

        tool_count = len(self._tool_map)
        logger.info(f"Plugin registered: {name} ({tool_count} tools)")

    async def unregister_plugin(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            return
        await plugin.shutdown()
        self._tool_map = {k: v for k, v in self._tool_map.items() if v != name}
        self._resource_map = {
            k: v for k, v in self._resource_map.items() if v != name
        }
        self._prompt_map = {
            k: v for k, v in self._prompt_map.items() if v != name
        }

    async def get_all_tools(self, context: dict | None = None) -> list[dict]:
        tools = []
        for plugin_name, plugin in self._plugins.items():
            for tool in await plugin.get_tools(context):
                tool["_plugin"] = plugin_name
                tools.append(tool)
        return tools

    def get_all_resources(self) -> list[dict]:
        resources = []
        for plugin in self._plugins.values():
            resources.extend(plugin.get_resources())
        return resources

    def get_all_prompts(self) -> list[dict]:
        prompts = []
        for plugin in self._plugins.values():
            prompts.extend(plugin.get_prompts())
        return prompts

    async def execute_tool(
        self,
        name: str,
        arguments: dict,
        on_progress: Callable[[int, int, str], None] | None = None,
        context: dict | None = None,
    ) -> dict:
        plugin_name = self._tool_map.get(name)

        # Check dynamic tools
        if plugin_name is None:
            for pname, plugin in self._plugins.items():
                if plugin.can_handle_tool(name):
                    plugin_name = pname
                    break

        if plugin_name is None:
            raise protocol.ProtocolError(
                f"Unknown tool: {name}", protocol.METHOD_NOT_FOUND
            )

        # Enforce allowed_plugins restriction
        if context and context.get("allowed_plugins") is not None:
            if plugin_name not in context["allowed_plugins"]:
                raise protocol.ProtocolError(
                    f"Plugin access denied: {plugin_name}",
                    protocol.INVALID_PARAMS,
                )

        plugin = self._plugins[plugin_name]
        if context:
            arguments["_context"] = context
        return await plugin.execute_tool(name, arguments, on_progress)

    async def read_resource(self, uri: str) -> dict:
        plugin_name = self._resource_map.get(uri)
        if plugin_name is None:
            raise protocol.ProtocolError(
                f"Unknown resource: {uri}", protocol.INVALID_PARAMS
            )
        return await self._plugins[plugin_name].read_resource(uri)

    async def get_prompt(self, name: str, arguments: dict) -> dict:
        plugin_name = self._prompt_map.get(name)
        if plugin_name is None:
            raise protocol.ProtocolError(
                f"Unknown prompt: {name}", protocol.INVALID_PARAMS
            )
        return await self._plugins[plugin_name].get_prompt(name, arguments)

    def has_tools(self) -> bool:
        return bool(self._tool_map) or any(
            p.can_handle_tool("ghost_") for p in self._plugins.values()
        )

    def has_resources(self) -> bool:
        return bool(self._resource_map)

    def has_prompts(self) -> bool:
        return bool(self._prompt_map)

    def get_plugin_names(self) -> list[str]:
        return list(self._plugins.keys())

    async def shutdown(self) -> None:
        for name, plugin in self._plugins.items():
            logger.info(f"Shutting down plugin: {name}")
            await plugin.shutdown()
        self._plugins.clear()
