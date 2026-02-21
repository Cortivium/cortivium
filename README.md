<h1 align="center">Cortivium</h1>

<p align="center">
  <strong>The most reliable way to control AI behavior.</strong>
  <br />
  Ghost Skills register as real MCP tools — not suggestions the model can ignore,<br />but contracts it reads before every action. More reliable than system prompts,<br />CLAUDE.md files, memory, or anything in the context window.
</p>

<p align="center">
  <a href="https://cortivium.com">Website</a> &nbsp;&middot;&nbsp;
  <a href="https://cortivium.com/docs/">Documentation</a> &nbsp;&middot;&nbsp;
  <a href="https://cortivium.com/ghost-skills/">Ghost Skills Guide</a> &nbsp;&middot;&nbsp;
  <a href="#quick-start">Quick Start</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/MCP-2024--11--05-purple?style=flat-square" alt="MCP Protocol">
  <img src="https://img.shields.io/badge/dependencies-8-orange?style=flat-square" alt="Dependencies">
</p>

---

## Why Ghost Skills?

System prompts drift. CLAUDE.md files get ignored in long sessions. Memory instructions compete with conversation context and lose. These approaches inject **advisory text** — the model treats them as suggestions.

Ghost Skills take a fundamentally different approach. They register as **real MCP tools** with descriptions the model reads every time it considers an action. Tool descriptions aren't suggestions — they're API contracts the model follows.

```
You:    "Create a ghost skill that enforces our code standards
         after every file edit"

Claude: [Creates ghost_code_standards]
        Description: "MANDATORY: After every Edit or Write, verify
        snake_case functions, PascalCase classes, grouped imports..."

        → Now fires automatically after every code change.
        → Not a reminder. An enforceable behavioral rule.
```

### Behavioral Reliability

| Approach | Reliability | Why |
|----------|:-----------:|-----|
| In-context rules | ~30% | Buried in conversation, first to be dropped |
| Memory / CLAUDE.md | ~55% | Loaded at session start, fades with context length |
| System prompts | ~65% | Persistent but advisory — model can override |
| **Ghost Skills (MCP tools)** | **~95%** | **Read before every action decision — treated as API contract** |

### Two Types of Ghost Skills

**Trigger Skills** respond to explicit commands:
> *"ship it"* → stages, commits, pushes, opens PR

**Behavioral Hooks** detect situations and auto-fire:
> *"after every file edit"* → enforces code standards automatically

Both are just Ghost Skills — the only difference is how you write the description.

---

## Quick Start

```bash
git clone https://github.com/Cortivium/cortivium.git
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

Create an API key in the admin panel, then:

```bash
claude mcp add --transport http --scope user cortivium \
  https://your-server:8080/ --header "X-API-Key: YOUR_KEY"
```

Or add manually to `~/.claude.json`:

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

Works with **Claude Code**, **Codex**, **Cursor**, and any MCP-compatible client.

---

## Ghost Skills

Ghost Skills are persistent AI tool registrations you create through conversation. Describe what you want in plain language — the AI handles the name, parameters, trigger phrases, and everything else.

### Create a Skill

```
You: "Create a ghost skill called commit_changes that commits my code
     with a descriptive message based on the diff"

Claude: [Calls ghost_create_skill]
        "Created ghost_commit_changes! Say 'commit my changes' to use it."
```

No JSON. No config files. No server restart.

### Automatic Trigger Phrases

Cortivium auto-generates trigger phrases from your skill name, description, and instructions:

| Source | Example Input | Generated Phrase |
|--------|---------------|------------------|
| Name | `review_pr` | `"review pr"` |
| Description | `"Review a pull request for bugs"` | `"review a pull request for bugs"` |
| Instructions | `"Check the diff for obvious bugs..."` | `"check the diff for"` |

Override anytime with your own `trigger_phrases` array.

### Use a Skill

Skills appear as real MCP tools. The AI calls them automatically:

```
You: "commit my changes"

Claude: [Calls ghost_commit_changes]
        [Follows your instructions exactly]
        "Done! Committed with message: 'Add user authentication middleware'"
```

### Example Use Cases

| Skill | What It Does |
|-------|-------------|
| `ghost_finish_coding` | Stage changes, write conventional commit, push branch, create PR |
| `ghost_code_standards` | Enforce naming patterns, error handling style, import ordering |
| `ghost_plan_feature` | Break features into subtasks with acceptance criteria before coding |
| `ghost_quality_check` | Run linter, type checks, tests, and security scan before marking done |
| `ghost_try_options` | Spin up git worktrees to try multiple approaches in parallel |
| `ghost_persist_tasklist` | Auto-save task state to disk so it survives context compaction |

### Manage Skills

| Tool | Description |
|------|-------------|
| `ghost_create_skill` | Create a new skill with instructions |
| `ghost_list_skills` | List all your skills |
| `ghost_update_skill` | Modify an existing skill |
| `ghost_delete_skill` | Delete a skill |

Skills are tied to your API key — private to you, portable across machines, available in every session.

---

## Highlights

- **~3,000 lines of Python** — no framework bloat, eight pip dependencies, starts in under a second
- **Zero infrastructure** — SQLite + in-memory rate limiting. No Redis, no MySQL, no message queue
- **Self-bootstrapping** — `python server.py` creates the database, runs migrations, generates credentials
- **Production ready** — TLS, async I/O, WAL-mode SQLite, SSE streaming, usage logging, Docker-native
- **Secure by default** — SHA-256 key hashing, CSRF protection, signed sessions, 3-tier rate limiting, per-key plugin isolation

## Admin Panel

Built-in dark-themed web interface at `/admin/`:

| Page | Features |
|------|----------|
| **Dashboard** | Server stats, recent activity, top tools chart (7-day) |
| **API Keys** | Create/edit/toggle/delete keys, shown once on creation |
| **Ghost Skills** | Browse, create, edit, toggle, delete skills with execution counts |
| **Plugins** | View loaded plugins with version and call stats |
| **Usage Logs** | Searchable request logs with filters, paginated |
| **Users** | Create/edit/delete users, set access levels |

Regular users get a scoped panel at `/user/` — own keys and skills only, no admin pages visible.

## Docker

```bash
docker build -t cortivium .
docker run -p 8080:8080 -v cortivium_data:/app/storage cortivium

# Or with compose
docker compose up -d
```

For HTTPS, mount your certificates:

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

## Configuration

All settings use the `CORTIVIUM_` prefix. No configuration required — sensible defaults out of the box.

| Variable | Default | Description |
|----------|---------|-------------|
| `CORTIVIUM_HOST` | `0.0.0.0` | Bind address |
| `CORTIVIUM_PORT` | `8080` | Server port |
| `CORTIVIUM_SECRET_KEY` | *(auto-generated)* | Session signing key |
| `CORTIVIUM_DATABASE_PATH` | `storage/cortivium.db` | SQLite database path |
| `CORTIVIUM_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |
| `CORTIVIUM_SSL_CERT` | *(empty)* | Path to SSL certificate |
| `CORTIVIUM_SSL_KEY` | *(empty)* | Path to SSL private key |

## Security

| Layer | Implementation |
|-------|---------------|
| **API Keys** | SHA-256 hashed — raw keys never stored |
| **Rate Limiting** | 3-tier throttling (per-minute/hour/day) per key |
| **Sessions** | Signed cookies via itsdangerous |
| **CSRF** | Double-submit cookie pattern on all mutations |
| **Passwords** | bcrypt with automatic salt |
| **Skill Isolation** | Ghost Skills scoped to creating API key — invisible to others |
| **Plugin Isolation** | Per-key `allowed_plugins` restricts tool access |
| **TLS** | Native HTTPS via Uvicorn |
| **Input Validation** | Strict schema validation on all MCP requests |

## Plugin Development

Extend with custom plugins. Each can register tools, resources, and prompts:

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
        result = arguments.get("input", "")
        return self.text_content(f"Processed: {result}")
```

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
            JSON Response  ─or─  SSE Stream
                  ↓
            Usage Logging → SQLite
```

| Component | Technology |
|-----------|-----------|
| Web framework | FastAPI + Uvicorn (async) |
| Database | SQLite via aiosqlite (WAL mode) |
| Admin panel | Jinja2 + Bulma CSS |
| API key auth | SHA-256 hashing, in-memory cache |
| Session auth | Signed cookies (itsdangerous) |
| Rate limiting | In-memory dict with TTL cleanup |
| Password hashing | bcrypt |

## Project Structure

```
cortivium/
├── server.py                    # Entry point
├── requirements.txt             # 8 dependencies
├── .env.example                 # Configuration template
├── Dockerfile
├── docker-compose.yml
├── migrations/
│   └── 001_initial.sql          # SQLite schema
└── cortivium/
    ├── core/                    # Server core (config, auth, sessions, protocol)
    ├── transport/               # MCP HTTP routes
    ├── plugin/                  # Plugin system (interface, base, manager)
    ├── plugins/
    │   ├── ghost_ootm/          # Ghost Skills — CRUD + dynamic tools
    │   └── example/             # Example plugin template
    ├── admin/                   # Web panel (routes, templates, static)
    └── util/                    # Async subprocess wrapper
```

## Contributing

Contributions welcome. Please open an issue first to discuss what you'd like to change.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run the server locally to verify (`python server.py`)
5. Commit and push
6. Open a Pull Request

## License

[Apache 2.0](LICENSE)

"Cortivium" and "Ghost Skills" are trademarks of Cortivium.
