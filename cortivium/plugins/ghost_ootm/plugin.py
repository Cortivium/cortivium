"""Ghost OOTM (Ghost Out Of The Machine) Plugin.

Enables users to create, store, and execute "ghost skills" —
portable instruction sets that register as individual MCP tools tied to their API key.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ...core.database import Database
from ...plugin.base import AbstractPlugin

logger = logging.getLogger("cortivium.ghost")

SESSION_EXPIRY = 3600  # 1 hour


class Plugin(AbstractPlugin):
    def get_name(self) -> str:
        return "ghost-ootm"

    async def initialize(self, config: dict, db: Any) -> None:
        await super().initialize(config, db)

    def can_handle_tool(self, name: str) -> bool:
        return name.startswith("ghost_")

    async def get_tools(self, context: dict | None = None) -> list[dict]:
        tools = self._get_static_tools()
        if context and context.get("api_key_id") and self._db:
            try:
                dynamic = await self._get_dynamic_tools(int(context["api_key_id"]))
                tools.extend(dynamic)
            except (ValueError, TypeError):
                pass
        return tools

    def _get_static_tools(self) -> list[dict]:
        return [
            {
                "name": "ghost_create_skill",
                "description": "Create a new ghost skill with custom instructions. Skills are plain-text guidance that the AI follows to complete tasks.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": 'Skill identifier (lowercase, underscores, e.g., "download_webpage")',
                        },
                        "description": {
                            "type": "string",
                            "description": "What this skill helps accomplish (shown in tools list)",
                        },
                        "instructions": {
                            "type": "string",
                            "description": "The skill instructions - plain text guidance for the AI to follow",
                        },
                        "trigger_phrases": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Natural language phrases that should invoke this skill",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "Optional: dynamic {{param}} definitions for runtime substitution",
                        },
                    },
                    "required": ["name", "description", "instructions"],
                },
            },
            {
                "name": "ghost_list_skills",
                "description": "List all ghost skills available for your account",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_disabled": {
                            "type": "boolean",
                            "description": "Include disabled skills in the list",
                            "default": False,
                        }
                    },
                },
            },
            {
                "name": "ghost_delete_skill",
                "description": "Delete a ghost skill",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the ghost skill to delete",
                        }
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "ghost_update_skill",
                "description": "Update an existing ghost skill",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the ghost skill to update",
                        },
                        "new_name": {
                            "type": "string",
                            "description": "New name (optional)",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description (optional)",
                        },
                        "instructions": {
                            "type": "string",
                            "description": "New instructions (optional)",
                        },
                        "is_enabled": {
                            "type": "boolean",
                            "description": "Enable or disable the skill",
                        },
                    },
                    "required": ["name"],
                },
            },
        ]

    async def _get_dynamic_tools(self, api_key_id: int) -> list[dict]:
        tools = []
        try:
            items = await self._db.query(
                "SELECT name, display_name, description, type, parameters "
                "FROM ghost_scripts WHERE api_key_id = ? AND is_enabled = 1",
                (api_key_id,),
            )
            for item in items:
                tool: dict[str, Any] = {
                    "name": f"ghost_{item['name']}",
                    "description": item["description"]
                    or f"Execute ghost skill: {item['display_name']}",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                }
                if item.get("parameters"):
                    try:
                        params = json.loads(item["parameters"])
                    except (json.JSONDecodeError, TypeError):
                        params = {}
                    if isinstance(params, dict) and params:
                        properties = {}
                        required = []
                        for pname, pdef in params.items():
                            properties[pname] = {
                                "type": pdef.get("type", "string"),
                                "description": pdef.get("description", ""),
                            }
                            if pdef.get("required"):
                                required.append(pname)
                        tool["inputSchema"]["properties"] = properties
                        tool["inputSchema"]["required"] = required
                tools.append(tool)
        except Exception as exc:
            logger.error(f"Failed to fetch dynamic tools: {exc}")
        return tools

    async def execute_tool(
        self,
        name: str,
        arguments: dict,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        context = arguments.pop("_context", {})
        api_key_id = context.get("api_key_id")

        match name:
            case "ghost_create_skill":
                return await self._handle_create_skill(api_key_id, arguments)
            case "ghost_list_skills":
                return await self._handle_list(api_key_id, arguments)
            case "ghost_delete_skill":
                return await self._handle_delete(api_key_id, arguments)
            case "ghost_update_skill":
                return await self._handle_update(api_key_id, arguments)
            case "ghost_create_start" | "ghost_create_script_start":
                return await self._handle_create_script_start(api_key_id, arguments)
            case "ghost_create_step" | "ghost_create_script_step":
                return await self._handle_create_script_step(api_key_id, arguments)
            case "ghost_create_finalize" | "ghost_create_script_finalize":
                return await self._handle_create_script_finalize(api_key_id, arguments)
            case _ if name.startswith("ghost_"):
                item_name = name[6:]  # Remove 'ghost_' prefix
                return await self._handle_execute(
                    api_key_id, item_name, arguments, on_progress
                )
            case _:
                return self.error_content(f"Unknown tool: {name}")

    # =========================================================================
    # Skill Handlers
    # =========================================================================

    async def _handle_create_skill(
        self, api_key_id: int | None, args: dict
    ) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required to create ghost skills.")

        name = args.get("name", "")
        description = args.get("description", "")
        instructions = args.get("instructions", "")
        trigger_phrases = args.get("trigger_phrases") or []
        parameters = args.get("parameters")

        # Auto-generate trigger phrases from name, description, and instructions
        if not trigger_phrases:
            trigger_phrases = self._generate_trigger_phrases(name, description, instructions)

        if not name:
            return self.error_content("Name is required.")
        if not description:
            return self.error_content("Description is required.")
        if not instructions:
            return self.error_content("Instructions are required.")

        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            return self.error_content(
                "Invalid name format. Use lowercase letters, numbers, and underscores. Must start with a letter."
            )

        try:
            existing = await self._db.query_one(
                "SELECT id FROM ghost_scripts WHERE api_key_id = ? AND name = ?",
                (api_key_id, name),
            )
            if existing:
                return self.error_content(
                    f"A ghost skill with name '{name}' already exists. Choose a different name or delete the existing one first."
                )

            await self._db.insert(
                "ghost_scripts",
                {
                    "api_key_id": api_key_id,
                    "name": name,
                    "display_name": name,
                    "description": description,
                    "type": "skill",
                    "instructions": instructions,
                    "trigger_phrases": json.dumps(trigger_phrases),
                    "parameters": json.dumps(parameters) if parameters else None,
                },
            )

            tool_name = f"ghost_{name}"
            phrases = trigger_phrases or [name]
            phrase_str = ", ".join(f'"{p}"' for p in phrases)
            audit = self._audit_skill(name, description, instructions, trigger_phrases)

            response = (
                f"## Ghost Skill Created\n\n"
                f"**Tool name:** `{tool_name}`\n"
                f"**Description:** {description}\n\n"
                f"The skill is now available. You can invoke it by calling `{tool_name}` or saying things like:\n"
                f"{phrase_str}"
            )

            if audit:
                response += "\n\n---\n\n## Skill Effectiveness Audit\n\n"
                for item in audit:
                    icon = "+" if item["level"] == "good" else ("!" if item["level"] == "warn" else "-")
                    response += f"[{icon}] **{item['category']}:** {item['message']}\n\n"

            return self.text_content(response)
        except Exception as exc:
            return self.error_content(f"Failed to create ghost skill: {exc}")

    async def _handle_list(self, api_key_id: int | None, args: dict) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required to list ghost skills.")

        include_disabled = args.get("include_disabled", False)

        try:
            sql = (
                "SELECT name, display_name, description, type, is_enabled, "
                "execution_count, last_executed_at, created_at, updated_at "
                "FROM ghost_scripts WHERE api_key_id = ?"
            )
            params: list = [api_key_id]

            if not include_disabled:
                sql += " AND is_enabled = 1"

            sql += " ORDER BY name ASC"
            items = await self._db.query(sql, params)

            if not items:
                return self.text_content(
                    "No ghost skills found.\n\nUse `ghost_create_skill` to create your first custom skill."
                )

            output = "## Your Ghost Skills\n\n"
            for item in items:
                status = "" if item["is_enabled"] else " (disabled)"
                exec_count = item["execution_count"] or 0
                last_run = (
                    f" | Last run: {item['last_executed_at']}"
                    if item["last_executed_at"]
                    else ""
                )
                output += f"**ghost_{item['name']}**{status}\n"
                output += f"{item['description']}\n"
                output += f"*Executions: {exec_count}{last_run}*\n\n"

            output += "---\n*Use a tool name (e.g., `ghost_{name}`) to execute, or `ghost_update_skill` / `ghost_delete_skill` to manage.*"
            return self.text_content(output)
        except Exception as exc:
            return self.error_content(f"Database error: {exc}")

    async def _handle_delete(self, api_key_id: int | None, args: dict) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required.")

        name = args.get("name", "")
        if not name:
            return self.error_content("Name is required.")

        if name.startswith("ghost_"):
            name = name[6:]

        try:
            rows = await self._db.execute(
                "DELETE FROM ghost_scripts WHERE api_key_id = ? AND name = ?",
                (api_key_id, name),
            )
            if rows == 0:
                return self.error_content(f"Ghost skill '{name}' not found.")
            return self.text_content(f"Ghost skill `ghost_{name}` deleted successfully.")
        except Exception as exc:
            return self.error_content(f"Failed to delete: {exc}")

    async def _handle_update(self, api_key_id: int | None, args: dict) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required.")

        name = args.get("name", "")
        if not name:
            return self.error_content("Name is required.")

        if name.startswith("ghost_"):
            name = name[6:]

        try:
            item = await self._db.query_one(
                "SELECT * FROM ghost_scripts WHERE api_key_id = ? AND name = ?",
                (api_key_id, name),
            )
            if not item:
                return self.error_content(f"Ghost skill '{name}' not found.")

            updates = {}
            if "new_name" in args:
                new_name = args["new_name"]
                if not re.match(r"^[a-z][a-z0-9_]*$", new_name):
                    return self.error_content("Invalid name format.")
                dup = await self._db.query_one(
                    "SELECT id FROM ghost_scripts WHERE api_key_id = ? AND name = ? AND id != ?",
                    (api_key_id, new_name, item["id"]),
                )
                if dup:
                    return self.error_content(
                        f"A ghost skill with name '{new_name}' already exists."
                    )
                updates["name"] = new_name

            if "description" in args:
                updates["description"] = args["description"]
            if "instructions" in args:
                updates["instructions"] = args["instructions"]
            if "commands" in args:
                updates["commands"] = json.dumps(args["commands"])
            if "is_enabled" in args:
                updates["is_enabled"] = 1 if args["is_enabled"] else 0

            if not updates:
                return self.error_content(
                    "No updates provided. Specify at least one field to update."
                )

            updates["updated_at"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            await self._db.update("ghost_scripts", updates, "id = ?", [item["id"]])

            updated_name = args.get("new_name", name)

            # Re-fetch and audit the updated skill
            updated = await self._db.query_one(
                "SELECT * FROM ghost_scripts WHERE api_key_id = ? AND name = ?",
                (api_key_id, updated_name),
            )

            response = f"Ghost skill `ghost_{updated_name}` updated successfully."

            if updated:
                audit = self._audit_skill(
                    updated["name"],
                    updated.get("description", ""),
                    updated.get("instructions", ""),
                    json.loads(updated.get("trigger_phrases") or "[]"),
                )
                if audit:
                    response += "\n\n---\n\n## Skill Effectiveness Audit\n\n"
                    for a in audit:
                        icon = "+" if a["level"] == "good" else ("!" if a["level"] == "warn" else "-")
                        response += f"[{icon}] **{a['category']}:** {a['message']}\n\n"

            return self.text_content(response)
        except Exception as exc:
            return self.error_content(f"Failed to update: {exc}")

    # =========================================================================
    # Execution Handler
    # =========================================================================

    async def _handle_execute(
        self,
        api_key_id: int | None,
        item_name: str,
        arguments: dict,
        on_progress: Callable | None,
    ) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required.")

        try:
            item = await self._db.query_one(
                "SELECT * FROM ghost_scripts WHERE api_key_id = ? AND name = ? AND is_enabled = 1",
                (api_key_id, item_name),
            )
            if not item:
                return self.error_content(f"Ghost skill not found: {item_name}")

            if item["type"] == "skill":
                response = self._build_skill_response(item, arguments)
            else:
                response = self._build_script_response(item, arguments)

            await self._db.execute(
                "UPDATE ghost_scripts SET execution_count = execution_count + 1, "
                "last_executed_at = datetime('now') WHERE id = ?",
                (item["id"],),
            )
            return self.text_content(response)
        except Exception as exc:
            return self.error_content(f"Database error: {exc}")

    @staticmethod
    def _generate_trigger_phrases(name: str, description: str, instructions: str) -> list[str]:
        """Generate trigger phrases from skill name, description, and instructions."""
        phrases: list[str] = []
        seen: set[str] = set()

        def _add(phrase: str) -> None:
            p = phrase.strip().lower()
            if p and p not in seen and len(p) > 1:
                seen.add(p)
                phrases.append(p)

        # 1. Natural form of the name: "say_hello" → "say hello"
        natural = name.replace("_", " ")
        _add(natural)

        # 2. Description often IS the best trigger — use it if short enough
        if description:
            desc_lower = description.strip().rstrip(".")
            # Use the full description if it's concise (≤60 chars)
            if len(desc_lower) <= 60:
                _add(desc_lower)
            # Extract the first verb phrase: "Say hello to the user..." → "say hello"
            # Take first 3-5 words as a short trigger
            words = desc_lower.split()
            if len(words) >= 2:
                _add(" ".join(words[:3]))
                if len(words) >= 5:
                    _add(" ".join(words[:5]))

        # 3. Pull key action phrases from the first sentence of instructions
        if instructions:
            first_line = instructions.split("\n")[0].strip().rstrip(".")
            if first_line and len(first_line) <= 80:
                words = first_line.split()
                if len(words) >= 2:
                    _add(" ".join(words[:4]))

        # Always include the raw name as fallback
        if name not in seen:
            _add(name)

        return phrases

    @staticmethod
    def _audit_skill(
        name: str, description: str, instructions: str, trigger_phrases: list[str]
    ) -> list[dict]:
        """Audit a ghost skill for effectiveness.

        Checks description, trigger phrases, and instructions to ensure
        the AI will discover and use the skill as intended.

        Returns a list of {level: good|warn|fix, category: str, message: str}.
        """
        audit: list[dict] = []

        # --- Description quality ---
        desc_len = len(description)
        if desc_len < 15:
            audit.append({
                "level": "fix",
                "category": "Description too short",
                "message": (
                    f"At {desc_len} chars, the AI may not understand when to call this tool. "
                    "The description appears in the tools list — make it specific and actionable."
                ),
            })
        elif desc_len > 200:
            audit.append({
                "level": "warn",
                "category": "Description very long",
                "message": (
                    f"At {desc_len} chars, the description may get truncated. "
                    "Keep it under 200 chars and put details in instructions."
                ),
            })
        else:
            audit.append({
                "level": "good",
                "category": "Description length",
                "message": f"Good length ({desc_len} chars) — descriptive enough for AI tool discovery.",
            })

        # --- Auto-activation language ---
        directive_words = [
            "must", "always", "mandatory", "required",
            "automatically", "every time", "after every",
        ]
        desc_lower = description.lower()
        has_directive = any(w in desc_lower for w in directive_words)

        instr_lower = instructions.lower()
        auto_trigger_patterns = [
            "after every", "whenever", "each time",
            "always call", "must call", "automatically",
        ]
        wants_auto = any(p in instr_lower for p in auto_trigger_patterns)

        if wants_auto and not has_directive:
            audit.append({
                "level": "fix",
                "category": "Auto-activation intent detected",
                "message": (
                    "Instructions suggest this skill should trigger automatically, but the "
                    "description lacks directive language. The AI decides whether to call tools "
                    "based on the **description** (not instructions). Add words like MUST, ALWAYS, "
                    'or MANDATORY to the description. Example: "MANDATORY: Call this after every '
                    'TaskCreate/TaskUpdate."'
                ),
            })
        elif has_directive:
            audit.append({
                "level": "good",
                "category": "Auto-activation",
                "message": "Description uses directive language — the AI is more likely to call this tool proactively.",
            })

        # --- Trigger phrases ---
        if not trigger_phrases:
            audit.append({
                "level": "warn",
                "category": "No trigger phrases",
                "message": "No trigger phrases defined. Auto-generated phrases were used, but custom ones match user intent better.",
            })
        elif len(trigger_phrases) < 3:
            audit.append({
                "level": "warn",
                "category": "Few trigger phrases",
                "message": (
                    f"Only {len(trigger_phrases)} trigger phrase(s). Consider adding more "
                    "variations of how a user might ask for this skill."
                ),
            })
        else:
            audit.append({
                "level": "good",
                "category": "Trigger phrases",
                "message": f"{len(trigger_phrases)} trigger phrases — good coverage.",
            })

        # --- Instructions quality ---
        if len(instructions) < 30:
            audit.append({
                "level": "warn",
                "category": "Instructions very brief",
                "message": (
                    f"Only {len(instructions)} chars of instructions. The AI may not have "
                    "enough guidance to complete the task correctly."
                ),
            })

        # --- Parameter placeholders ---
        param_matches = re.findall(r"\{\{(\w+)\}\}", instructions)
        if param_matches:
            unique = list(dict.fromkeys(param_matches))
            params_str = "}}, {{".join(unique)
            audit.append({
                "level": "good",
                "category": "Dynamic parameters",
                "message": f"Uses {{{{{params_str}}}}} — values will be substituted at runtime.",
            })

        # --- Name conflicts ---
        reserved = [
            "create_skill", "list_skills", "delete_skill", "update_skill",
            "create_start", "create_step", "create_finalize",
            "create_script_start", "create_script_step", "create_script_finalize",
        ]
        if name in reserved:
            audit.append({
                "level": "fix",
                "category": "Name conflict",
                "message": (
                    f"Name '{name}' conflicts with a built-in ghost tool "
                    f"(ghost_{name}). Choose a different name."
                ),
            })

        return audit

    def _build_skill_response(self, skill: dict, arguments: dict) -> str:
        display_name = skill.get("display_name") or skill["name"]
        instructions = skill.get("instructions") or ""

        for key, value in arguments.items():
            if isinstance(value, str) and not key.startswith("_"):
                instructions = instructions.replace("{{" + key + "}}", value)

        response = f"## Skill: {display_name}\n\n"
        response += "Follow these instructions to complete the task:\n\n"
        response += "---\n\n"
        response += instructions
        response += "\n\n---\n"

        provided = {
            k: v for k, v in arguments.items() if not k.startswith("_")
        }
        if provided:
            response += "\n**Parameters provided:**\n"
            for k, v in provided.items():
                response += f"- `{k}`: {v}\n"

        return response

    def _build_script_response(self, script: dict, arguments: dict) -> str:
        display_name = script.get("display_name") or script["name"]
        try:
            commands = json.loads(script.get("commands") or "[]")
        except (json.JSONDecodeError, TypeError):
            commands = []

        if not commands:
            return "Error: Ghost script has no commands defined."

        script_content = self._build_execution_script(commands, arguments)

        response = f"## Ghost Script: {display_name}\n\n"
        response += "Execute the following commands exactly as shown:\n\n"
        response += f"```bash\n{script_content}\n```\n\n"
        response += (
            f"**Instructions:** Write this script to a temporary file "
            f"(e.g., `/tmp/ghost_{script['name']}.sh`) and execute it with "
            f"`bash /tmp/ghost_{script['name']}.sh`. Do not modify the commands."
        )
        return response

    def _build_execution_script(
        self, commands: list, arguments: dict
    ) -> str:
        lines = ["#!/bin/bash", "set -e", ""]

        for cmd in commands:
            if isinstance(cmd, dict):
                command = cmd.get("cmd") or cmd.get("command", "")
                description = cmd.get("description", "")
            else:
                command = str(cmd)
                description = ""

            for key, value in arguments.items():
                if isinstance(value, str) and not key.startswith("_"):
                    from ...util.process import quote

                    command = command.replace("{{" + key + "}}", quote(value))

            if description:
                lines.append(f"# {description}")
            lines.append(command)
            lines.append("")

        lines.append('echo "Ghost script completed successfully."')
        return "\n".join(lines)

    # =========================================================================
    # Script Creation Handlers (Experimental)
    # =========================================================================

    async def _handle_create_script_start(
        self, api_key_id: int | None, args: dict
    ) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required to create ghost scripts.")

        intent = args.get("intent", "create a new automation")

        try:
            await self._cleanup_expired_sessions()
            session_token = secrets.token_hex(32)
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=SESSION_EXPIRY)
            ).strftime("%Y-%m-%d %H:%M:%S")

            await self._db.insert(
                "ghost_creation_sessions",
                {
                    "api_key_id": api_key_id,
                    "session_token": session_token,
                    "context": json.dumps({"intent": intent}),
                    "expires_at": expires_at,
                },
            )

            return self.text_content(
                f"## Creating a New Ghost Script (Experimental)\n\n"
                f"> **Note:** Ghost scripts execute commands verbatim. For most use cases, "
                f"consider using `ghost_create_skill` instead.\n\n"
                f"Session started. Token: `{session_token}`\n\n"
                f"**Intent:** {intent}\n\n"
                f"### Next Steps\n\n"
                f"1. Help the user test each command.\n"
                f"2. Record working commands with `ghost_create_script_step`.\n"
                f"3. Finalize with `ghost_create_script_finalize`.\n\n"
                f"**Session expires in 1 hour.**"
            )
        except Exception as exc:
            return self.error_content(f"Failed to start session: {exc}")

    async def _handle_create_script_step(
        self, api_key_id: int | None, args: dict
    ) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required.")

        session_token = args.get("session_token", "")
        command = args.get("command", "")
        description = args.get("description", "")

        if not session_token:
            return self.error_content("Session token is required.")
        if not command:
            return self.error_content("Command is required.")

        try:
            session = await self._db.query_one(
                "SELECT * FROM ghost_creation_sessions "
                "WHERE session_token = ? AND api_key_id = ? AND expires_at > datetime('now')",
                (session_token, api_key_id),
            )
            if not session:
                return self.error_content(
                    "Invalid or expired session. Start a new session with `ghost_create_script_start`."
                )

            try:
                commands = json.loads(session.get("commands") or "[]")
            except (json.JSONDecodeError, TypeError):
                commands = []
            commands.append({"cmd": command, "description": description})

            await self._db.update(
                "ghost_creation_sessions",
                {"commands": json.dumps(commands), "state": "recording_commands"},
                "id = ?",
                [session["id"]],
            )

            idx = len(commands)
            return self.text_content(
                f"**Command #{idx} recorded:**\n```\n{command}\n```\n"
                + (f"*{description}*\n\n" if description else "\n")
                + "Continue testing commands, or call `ghost_create_script_finalize` when done."
            )
        except Exception as exc:
            return self.error_content(f"Database error: {exc}")

    async def _handle_create_script_finalize(
        self, api_key_id: int | None, args: dict
    ) -> dict:
        if not api_key_id or not self._db:
            return self.error_content("Authentication required.")

        session_token = args.get("session_token", "")
        name = args.get("name", "")
        display_name = args.get("display_name", name)
        description = args.get("description", "")
        trigger_phrases = args.get("trigger_phrases") or []

        # Auto-generate trigger phrases from skill name if none provided
        if not trigger_phrases and name:
            trigger_phrases = self._generate_trigger_phrases(name, description, "")

        if not session_token:
            return self.error_content("Session token is required.")
        if not name:
            return self.error_content("Name is required.")
        if not description:
            return self.error_content("Description is required.")
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            return self.error_content("Invalid name format.")

        try:
            session = await self._db.query_one(
                "SELECT * FROM ghost_creation_sessions "
                "WHERE session_token = ? AND api_key_id = ? AND expires_at > datetime('now')",
                (session_token, api_key_id),
            )
            if not session:
                return self.error_content("Invalid or expired session.")

            try:
                commands = json.loads(session.get("commands") or "[]")
            except (json.JSONDecodeError, TypeError):
                commands = []
            if not commands:
                return self.error_content("No commands recorded.")

            existing = await self._db.query_one(
                "SELECT id FROM ghost_scripts WHERE api_key_id = ? AND name = ?",
                (api_key_id, name),
            )
            if existing:
                return self.error_content(f"Name '{name}' already exists.")

            await self._db.insert(
                "ghost_scripts",
                {
                    "api_key_id": api_key_id,
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                    "type": "script",
                    "trigger_phrases": json.dumps(trigger_phrases),
                    "commands": json.dumps(commands),
                },
            )

            await self._db.execute(
                "DELETE FROM ghost_creation_sessions WHERE id = ?",
                (session["id"],),
            )

            tool_name = f"ghost_{name}"
            return self.text_content(
                f"## Ghost Script Created (Experimental)\n\n"
                f"**Tool name:** `{tool_name}`\n"
                f"**Description:** {description}\n"
                f"**Commands:** {len(commands)}\n\n"
                f"The script is now available as `{tool_name}`."
            )
        except Exception as exc:
            return self.error_content(f"Failed to create script: {exc}")

    async def _cleanup_expired_sessions(self) -> None:
        try:
            await self._db.execute(
                "DELETE FROM ghost_creation_sessions WHERE expires_at < datetime('now')"
            )
        except Exception as exc:
            logger.error(f"Session cleanup error: {exc}")
