<p align="center">
  <h1 align="center">Cortivium</h1>
  <p align="center">
    A lightweight, self-deployable MCP server with Ghost Skills
    <br />
    <em>Taking the Ghost Out of the Machine</em>
  </p>
  <p align="center">
    <a href="#quick-start">Quick Start</a> &middot;
    <a href="#ghost-skills">Ghost Skills</a> &middot;
    <a href="#admin-panel">Admin Panel</a> &middot;
    <a href="#docker">Docker</a> &middot;
    <a href="#plugin-development">Plugins</a>
  </p>
</p>

---

Cortivium is a self-contained [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server that gives AI assistants persistent, custom tools through a plugin system. Its flagship feature, **Ghost Skills**, lets you create AI tool registrations through natural conversation — no code, no config files, no restart required.

Unlike system prompts or CLAUDE.md files that drift over long sessions, Ghost Skills register as real MCP tools. The model reads the tool description every time it considers an action, making them the most reliable way to control AI behavior.

## Highlights

- **Lightweight** — ~3,000 lines of Python. No framework bloat. Eight pip dependencies. Starts in under a second.
- **Zero Infrastructure** — SQLite database, in-memory rate limiting. No Redis, no MySQL, no message queue. One process, one binary, one volume.
- **Secure by Default** — SHA-256 API key hashing, CSRF protection, signed session cookies, 3-tier rate limiting (per-minute/hour/day), per-key plugin access control, and full API key isolation for Ghost Skills.
- **Self-Bootstrapping** — Run `python server.py` and it creates the database, runs migrations, generates a secret key, and prints admin credentials. Zero configuration needed.
- **Production Ready** — TLS support, async I/O throughout, WAL-mode SQLite for concurrent reads, SSE streaming for long-running tools, usage logging, and Docker-native deployment.

## Quick Start

```bash
git clone https://github.com/cortivium/cortivium.git
cd cortivium
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python server.py
```

On first run, Cortivium will:

1. Create the SQLite database and apply migrations
2. Generate a secret key and save it to `.env`
3. Create an admin user and **print the credentials to the console** — save them

Open `http://localhost:8080/admin/` and log in with the generated credentials.

### Connect from Claude Code

Create an API key in the admin panel, then add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "cortivium": {
      "type": "http",
      "url": "https://your-server:8080/",
      "headers": {
        "X-API-Key": "your-api-key"
      }
    }
  }
}
```

Restart Claude Code. Your tools will appear automatically.

## Ghost Skills

Ghost Skills are persistent AI tool registrations you create through conversation. They combine the **reliability of MCP tools** with the **flexibility of plain-text instructions**.

### Create a Skill

Just describe what you want in natural language:

```
You: "Create a ghost skill called commit_changes that commits my code
     with a descriptive message based on the diff"

Claude: [Calls ghost_create_skill]
        "Created ghost_commit_changes! Say 'commit my changes' to use it."
```

That's it. No JSON, no config files, no server restart.

### Automatic Trigger Phrases

When you create a skill, Cortivium automatically generates trigger phrases from the skill name, description, and instructions. You never need to think about how a skill gets invoked.

| Source | Example Input | Generated Phrase |
|--------|---------------|------------------|
| Name | `review_pr` | `"review pr"` |
| Description | `"Review a pull request for bugs"` | `"review a pull request for bugs"` |
| Instructions | `"Check the diff for obvious bugs..."` | `"check the diff for"` |

You can override this by providing your own `trigger_phrases` array during creation.

### Use a Skill

Skills appear as real MCP tools. The AI calls them automatically when your request matches:

```
You: "commit my changes"

Claude: [Calls ghost_commit_changes]
        [Receives your instructions, follows them]
        "Done! Committed with message: 'Add user authentication middleware'"
```

### Manage Skills

| Tool | Description |
|------|-------------|
| `ghost_create_skill` | Create a new skill with instructions |
| `ghost_list_skills` | List all your skills |
| `ghost_update_skill` | Modify an existing skill |
| `ghost_delete_skill` | Delete a skill |

Skills are tied to your API key — private to you, portable across machines, available in every session.

### Example Use Cases

| Skill | What It Does |
|-------|-------------|
| `ghost_finish_coding` | Stage changes, write conventional commit, push branch, create PR |
| `ghost_code_standards` | Enforce naming patterns, error handling style, import ordering |
| `ghost_plan_feature` | Break features into subtasks with acceptance criteria before coding |
| `ghost_quality_check` | Run linter, type checks, tests, and security scan before marking done |
| `ghost_try_options` | Spin up git worktrees to try multiple approaches in parallel |

## Admin Panel

Built-in web interface at `/admin/` with a dark theme (Bulma CSS):

| Page | Features |
|------|----------|
| **Dashboard** | Server stats (total keys, active keys, requests today/this hour), recent activity feed, top tools chart (7-day) |
| **API Keys** | Create keys (shown once — save immediately), edit name/description/owner, toggle active/inactive, delete |
| **Ghost Skills** | Browse all skills with filter-by-key dropdown, create/edit/toggle/delete skills, view execution counts |
| **Plugins** | View loaded plugins with version, tool count, total calls; enable/disable toggle |
| **Usage Logs** | Searchable request logs with filters (key prefix, tool name, status), paginated 50 per page |
| **Users** | Create/edit/delete users, set access levels, reset passwords |

### User Panel

Regular users (access level 2) get a separate panel at `/user/` with the same dark theme but scoped to their own data:

| Page | Features |
|------|----------|
| **Dashboard** | Stats for own API keys only — request counts, recent activity |
| **API Keys** | Create and manage own keys (cannot set owner email or see other users' keys) |
| **Ghost Skills** | Create and manage skills on own keys only |

Admin-only pages (Plugins, Usage Logs, Users) are not visible to regular users. Admins logging in are redirected to `/admin/`, regular users to `/user/`.

### Access Levels

| Level | Name | Permissions |
|-------|------|-------------|
| 0 | Disabled | Cannot log in |
| 1 | Pending | Cannot log in — awaiting admin approval |
| 2 | User | Own keys and skills via `/user/` panel |
| 3 | Admin | Full access to all pages via `/admin/` |
| 4 | Super Admin | Full access (reserved for future elevated permissions) |

## Security

Cortivium is designed for safe deployment on internal networks and public-facing servers alike:

| Layer | Implementation |
|-------|---------------|
| **API Key Storage** | SHA-256 hashed — raw keys are never stored |
| **Rate Limiting** | 3-tier throttling (per-minute, per-hour, per-day) per API key |
| **Session Auth** | Signed cookies via itsdangerous with configurable expiry |
| **CSRF Protection** | Double-submit cookie pattern on all admin mutations |
| **Key Expiration** | Optional expiry dates on API keys with automatic enforcement |
| **Plugin Isolation** | Per-key `allowed_plugins` restricts which tools a key can access |
| **Skill Isolation** | Ghost Skills are scoped to the creating API key — invisible to other keys |
| **Password Hashing** | bcrypt with automatic salt |
| **TLS** | Native HTTPS via Uvicorn — just set `CORTIVIUM_SSL_CERT` and `CORTIVIUM_SSL_KEY` |
| **Input Validation** | Strict schema validation on all MCP requests, safe parameter substitution |

## Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTIVIUM_HOST` | `0.0.0.0` | Bind address |
| `CORTIVIUM_PORT` | `8080` | Server port |
| `CORTIVIUM_SECRET_KEY` | *(auto-generated)* | Session signing key |
| `CORTIVIUM_DATABASE_PATH` | `storage/cortivium.db` | SQLite database path |
| `CORTIVIUM_STORAGE_PATH` | `storage` | Runtime data directory |
| `CORTIVIUM_LOG_LEVEL` | `info` | Logging level (`debug`, `info`, `warning`, `error`) |
| `CORTIVIUM_SSL_CERT` | *(empty)* | Path to SSL certificate for HTTPS |
| `CORTIVIUM_SSL_KEY` | *(empty)* | Path to SSL private key for HTTPS |

All settings use the `CORTIVIUM_` prefix. No configuration is required — the server runs with sensible defaults out of the box.

## Docker

```bash
# Build and run
docker build -t cortivium .
docker run -p 8080:8080 -v cortivium_data:/app/storage cortivium

# Or with docker compose
docker compose up -d
```

For HTTPS in Docker, mount your certificates:

```yaml
services:
  cortivium:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - cortivium_data:/app/storage
      - ./certs:/certs:ro
    environment:
      - CORTIVIUM_SSL_CERT=/certs/fullchain.pem
      - CORTIVIUM_SSL_KEY=/certs/privkey.pem
```

The Docker image is based on `python:3.12-slim` — minimal footprint, no unnecessary system packages.

## Plugin Development

Extend the server with custom plugins. Each plugin can register tools, resources, and prompts.

```python
from cortivium.plugin.base import AbstractPlugin

class Plugin(AbstractPlugin):
    def get_name(self) -> str:
        return "my-plugin"

    async def get_tools(self, context=None) -> list[dict]:
        return [{
            "name": "my_tool",
            "description": "Does something useful",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "The input"}
                },
                "required": ["input"]
            }
        }]

    async def execute_tool(self, name, arguments, on_progress=None):
        # on_progress(current, total, message) for SSE streaming
        result = arguments.get("input", "")
        return self.text_content(f"Processed: {result}")
```

Plugins support:
- **Async execution** — all methods are `async/await`
- **Progress streaming** — SSE callbacks for long-running tools via `on_progress`
- **Dynamic tools** — register tools at runtime (like Ghost Skills does)
- **Context injection** — receive `api_key_id` and metadata for per-user behavior
- **Subprocess execution** — `cortivium.util.process` for non-blocking shell commands

Register plugins in `cortivium/core/app.py` by adding to the plugin list.

## Architecture

```
HTTP Request → FastAPI/Uvicorn
                  ↓
            JSON-RPC 2.0 Parser (MCP 2024-11-05)
                  ↓
            API Key Auth + 3-Tier Rate Limiting
                  ↓
            Session Manager (in-memory, auto-expiry)
                  ↓
            PluginManager → Plugin.execute_tool()
                  ↓
            JSON Response  ─or─  SSE Stream (long-running)
                  ↓
            Usage Logging → SQLite
```

| Component | Technology |
|-----------|-----------|
| Web framework | FastAPI + Uvicorn (async) |
| Database | SQLite via aiosqlite (WAL mode) |
| Admin panel | Jinja2 + Bulma CSS |
| API key auth | SHA-256 hashing, in-memory cache (5-min TTL) |
| Session auth | Signed cookies (itsdangerous) |
| Rate limiting | In-memory dict with TTL cleanup |
| Password hashing | bcrypt |
| Subprocess | asyncio.create_subprocess_shell |

## Project Structure

```
cortivium/
├── server.py                    # Entry point: python server.py
├── requirements.txt             # 8 dependencies
├── .env.example                 # Configuration template
├── Dockerfile                   # python:3.12-slim based
├── docker-compose.yml
├── migrations/
│   └── 001_initial.sql          # SQLite schema
│
└── cortivium/
    ├── core/
    │   ├── app.py               # FastAPI app factory, lifespan, startup
    │   ├── config.py            # Pydantic Settings from .env
    │   ├── protocol.py          # JSON-RPC 2.0 / MCP protocol
    │   ├── session.py           # In-memory session manager
    │   ├── auth.py              # API key validation + rate limiting
    │   ├── database.py          # Async SQLite wrapper + migrations
    │   └── logger.py            # Logging configuration
    │
    ├── transport/
    │   └── mcp.py               # MCP HTTP routes (POST/DELETE/OPTIONS /)
    │
    ├── plugin/
    │   ├── interface.py         # PluginInterface ABC
    │   ├── base.py              # AbstractPlugin with helpers
    │   └── manager.py           # Tool/resource/prompt routing
    │
    ├── plugins/
    │   ├── ghost_ootm/          # Ghost Skills — CRUD + dynamic tools
    │   └── example/             # Example plugin template
    │
    ├── admin/
    │   ├── routes.py            # All admin panel routes
    │   ├── auth.py              # Login, logout, CSRF, sessions
    │   ├── templates/           # Jinja2 templates (9 pages)
    │   └── static/              # CSS dark theme + logo
    │
    └── util/
        └── process.py           # Async subprocess wrapper
```

## MCP Protocol

Implements **MCP 2024-11-05** (Streamable HTTP transport).

| Method | Description |
|--------|-------------|
| `initialize` | Client handshake and capability negotiation |
| `tools/list` | List available tools (static + dynamic ghost skills) |
| `tools/call` | Execute a tool (JSON response or SSE stream) |
| `resources/list` | List available resources |
| `resources/read` | Read a resource |
| `prompts/list` | List available prompts |
| `prompts/get` | Get a prompt |
| `ping` | Health check |

### Request Headers

| Header | Description |
|--------|-------------|
| `X-API-Key` | API key for authentication (required) |
| `Content-Type` | `application/json` (required) |
| `Mcp-Session-Id` | Session ID from `initialize` response |

### Response Headers

| Header | Description |
|--------|-------------|
| `Mcp-Session-Id` | Session identifier |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Seconds until rate limit resets |

## Database Schema

Cortivium uses SQLite with automatic migrations. The schema is defined in `migrations/001_initial.sql`.

| Table | Purpose |
|-------|---------|
| `users` | Admin/user accounts with bcrypt password hashes and access levels |
| `api_keys` | SHA-256 hashed keys with per-key rate limits, expiration, and plugin allowlists |
| `usage_logs` | Request audit trail — tool, plugin, status, duration, client IP, timestamps |
| `plugins` | Registered plugins with enable/disable state and call counters |
| `tools` | Tool metadata and per-tool call counters |
| `ghost_scripts` | Ghost Skills and Scripts — instructions, parameters, execution counts, per API key |
| `ghost_creation_sessions` | Temporary state for multi-step script creation (1-hour TTL) |
| `ghost_executions` | Ghost skill execution audit trail with parameters and duration |

## Requirements

- Python 3.12+
- No system dependencies required

## Contributing

Contributions are welcome. Please open an issue to discuss what you'd like to change before submitting a PR.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the server locally to verify (`python server.py`)
5. Commit and push (`git push origin feature/my-feature`)
6. Open a Pull Request

## License

[Apache 2.0](LICENSE)

"Cortivium" and "Ghost Skills" are trademarks of Cortivium.
