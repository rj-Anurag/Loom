# Loom

A context layer for the agentic era. Loom bridges browser AI chats (Claude.ai, ChatGPT) and CLI agents (Claude Code, opencode, etc.) into a shared, persistent context store. **Context is never lost, only compressed or deferred.**

## How It Works

Instead of manually pasting context between browser chats and your CLI:

```
You type in your CLI:        @loom implement the login feature

Loom automatically:
  ├─ Pulls context from browser AI chats (via extension)
  ├─ Pulls context from past agent sessions
  └─ Pulls context from local files
       │
       ▼
Your prompt is AUGMENTED with full context
       │
       ▼
AI responds with complete awareness — no re-explaining
```

## Quick Start

```bash
# 1. Install
git clone https://github.com/rj-Anurag/Loom
cd Loom
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# 2. Start infrastructure
docker compose -f infra/docker-compose.yml up -d
./scripts/migrate.sh up

# 3. Start Loom context server
uvicorn loom.api.main:app  # or: loom serve

# 4. Install browser extension (optional — enables browser chat sync)

# 5. Use in your CLI tool
# In Claude Code, opencode, or any AI CLI:
# > @loom implement the login feature
```

## Architecture

Loom is a modular monolith with an event-driven core:

- **Context Service** — Read/write context units, append-only event log
- **Coordination Service** — Branch/merge for concurrent agent writes
- **Retrieval Service** — Embedding generation, hybrid search, summarization
- **Agent Services** — Local, cloud, and browser agent runtimes
- **Browser Extension** — Bridges AI chat context into the store

See [loom-architecture.md](loom-architecture.md) for the full design, and [plans/](plans/) for the implementation roadmap.

## Project Structure

```
loom/
├── loom/                # Main Python package
│   ├── api/             # FastAPI context server API
│   ├── services/        # Business logic
│   └── agents/          # Agent runtimes
├── infra/               # Docker configs
├── tools/               # Orchestrator CLI
├── extension/           # Browser extension (Chrome/Firefox)
├── tests/               # Test suite
├── scripts/             # Utility scripts
├── plans/               # Implementation plans
├── .github/workflows/   # CI/CD
├── pyproject.toml       # Project config
└── loom-architecture.md # Architecture doc
```

## License

MIT
