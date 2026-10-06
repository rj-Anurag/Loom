# Loom

Loom is a project-scoped context layer for coding agents. It captures useful
history from browser AI conversations, stores it in a shared context graph, and
makes that context available to Codex, OpenCode, Claude Code, and other
MCP-capable clients.

The core rule is simple: one real software project has one Loom project ID.
Every browser chat and coding agent working on that software project connects
to that same ID with its own project-scoped API key.

## What is included

- FastAPI API with opaque bearer-key authentication
- PostgreSQL + pgvector context/event storage
- Redis embedding queues, presence, and coordination locks
- MCP tools and a reusable `loom` prompt
- CLI for initialization, retrieval, inspection, and harness installation
- Chrome MV3 extension for Claude, ChatGPT, DeepSeek, and Perplexity
- Project dashboard with context, active-agent, and conflict views
- Google self-service accounts with terminal-owned project creation

See the [Loom architecture guide](https://loom-docs.vercel.app/docs#context-flow)
for the detailed architecture.

## Install Loom as a user

Python 3.11 or newer and Git are required. Clone the repository so the unpacked
extension source and the system installer come from the same reviewed revision:

```bash
git clone https://github.com/rj-Anurag/Loom.git
cd Loom
```

On macOS or Linux:

```bash
./install.sh
```

On Windows PowerShell:

```powershell
.\install.ps1
```

Both installers use `pipx` to create an isolated, user-level environment and
never request administrator privileges. From a checkout they install that exact
checkout; the source can be overridden with `--source` on macOS/Linux or
`-Source` on Windows. Restart the terminal if needed, then verify:

```bash
loom --version
loom --help
```

Next, prepare the configured unpacked extension and print its directory:

```bash
loom extension install --api-url https://loom-api-zzy0.onrender.com
loom extension status --check-api
loom extension path
```

Load the printed directory in `chrome://extensions` using **Developer mode →
Load unpacked**. The installer-generated directory is used instead of loading
the checked-in `extension/` directory directly because it injects the server's
Chrome OAuth client ID and narrows host permissions to the selected API.

See the [Loom installation guide](https://loom-docs.vercel.app/docs#installation)
for upgrades, uninstalling, platform prerequisites, self-hosted servers, and
troubleshooting. This installs the client tools only; hosted users do not need
Docker, PostgreSQL, Redis, or a local API server.

## Public self-service quick start

Set the hosted server URL from inside the repository you want to connect:

```bash
export LOOM_API_URL="https://loom-api-zzy0.onrender.com"
loom login
loom init "My Project"
```

`loom login` opens Google in the system browser using Authorization Code with
PKCE. It creates or finds the Loom account and stores only the revocable Loom
session in `~/.loom/account.json`. It does not create a project or print an API
key.

`loom init` creates the project, owner membership, and a distinct local-agent
credential for this machine. The credential is stored with private permissions
in `~/.loom/projects.json`; Loom commands and the MCP server read it
automatically. The repository gets a commit-safe `.loom/project.json` containing
only its server and project identity, so different repositories cannot silently
use whichever project was selected most recently:

```bash
loom init "My Project" --install all
```

On another machine, sign in and select an existing project:

```bash
loom login
loom projects
loom switch <project-id>
```

## Local setup

Requirements: Python 3.11+, Docker with Compose, and Google Chrome or another
Chromium browser.

```bash
conda env create -f environment.yml
conda activate loom
cp .env.example .env

docker compose -f infra/docker-compose.yml up -d
./scripts/migrate.sh up
uvicorn loom.api.main:app --host 0.0.0.0 --port 8000
```

In another terminal, verify the server:

```bash
curl http://localhost:8000/health
# {"status":"ok"}

curl http://localhost:8000/ready
# {"database":"ok","redis":"ok"}
```

## Create the project and get its key

Run this inside the repository whose context you want Loom to share, after
`loom login`. Operators may still pass `--bootstrap` for self-hosted recovery:

```bash
conda activate loom
loom init "Loom" --install all
```

This creates or selects a real project, stores a distinct local-agent
credential privately, and installs the Codex, Claude Code, and OpenCode MCP
integrations. Harness installation never creates or modifies Markdown files.
The normal flow does not display the key or write credentials into the
repository. `.env` is reserved for server runtime configuration.

There is no separate **LOOP API key**. The product is named Loom. The server
generates a project-scoped `LOOM_API_KEY` for each CLI or browser installation,
returns it once, and stores only its SHA-256 digest. Never commit `.env` or
`~/.loom/projects.json`.

### Which project ID should I use?

Use `loom config` to see the project selected by `loom init` or `loom switch`.
Do not use an agent ID, chat ID, browser URL, or the internal
`__loom_extension__` bootstrap project.

To check the active project without exposing its full key:

```bash
loom config
loom projects
```

User sessions own and list projects. Runtime clients use separate project-scoped
API keys so every browser and coding agent retains its own audit identity.

## Browser extension

The CLI includes the complete extension and stages a configured, credential-free
copy from the cloned revision for the hosted MVP:

```bash
loom extension install --api-url https://loom-api-zzy0.onrender.com
loom extension status --check-api
loom extension path
```

Then:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select the directory printed by
   `loom extension path` (normally `~/.loom/extension`).
4. Open a conversation on Claude, ChatGPT, DeepSeek, or Perplexity.
5. Open Loom from the browser toolbar.
6. Choose **Continue with Google** using the same account used by `loom login`.
7. Loom loads the account projects and provisions a separate browser key.
8. Select the project and choose **Link conversation**.

The extension never creates a project. If the account has no projects, it
shows the exact terminal command `loom init "My Project"`; refresh the popup
after running it. The normal extension flow never asks the user to copy a
project ID or API key.

Manual project ID/API-key connection remains available under the advanced
section for older installations and self-hosted recovery.

Existing messages are backfilled immediately after linking. Loom combines all
known message layouts and briefly walks the conversation to the top so older
turns that the site loads lazily are materialized and captured; it then returns
the conversation to its prior scroll position. New messages are observed and
synced automatically. Loom also injects its scanner when the tab was open
before the extension was installed, so a manual refresh is not normally
required. Failed writes are held in a local retry queue and retried by the
extension background worker. The popup shows whether anything is still queued.
The dashboard reads the complete paginated history instead of the token-limited
agent retrieval view. Its read-only source explorer groups linked browser chats,
Codex sessions, OpenCode sessions, and legacy unscoped memory without changing
the stored context. Linked chats remain visible before their first message is
captured.

To reconfigure an existing install for another Loom server, repeat the install
with `--force`. Loom validates the server URL, replaces the existing extension
directory with the latest version, and updates Chrome's host permission:

```bash
loom extension install --api-url https://loom.example.com --force
```

To make a zip for private distribution or Chrome Web Store submission:

```bash
loom extension package \
  --api-url https://loom-api-zzy0.onrender.com \
  --output loom-extension.zip
```

The package command places `manifest.json` at the zip root and removes any
default credential. It discovers the server's Google Chrome client ID and
injects it into the package. Project API keys remain in Chrome's local
extension storage after Google authentication; they are never written into the
distributed bundle. For repository development, install through the CLI or
provide `--google-client-id`; the checked-in `extension/` directory deliberately
contains a non-working OAuth placeholder.

## Claude Code

`loom init --install all` creates:

- `.mcp.json` — project-local Loom MCP server with
  `LOOM_SOURCE_TYPE=claude_code`; it reads Loom's private user-level project
  configuration when environment variables are absent

After `loom login` and `loom init`, start Claude Code normally:

```bash
claude
```

Claude may ask you to approve the repository's project MCP server the first
time it opens. Claude can then call Loom's `read_context` and `write_context`
tools. Loom never creates or modifies project Markdown instruction files.

## OpenCode

Install OpenCode's project-local MCP registration from a connected repository:

```bash
loom install OpenCode
```

The installer creates or merges `opencode.json`, installs
`.opencode/plugins/loom.js`, and records writes as `opencode`,
and leaves unrelated configuration untouched. Existing `opencode.jsonc` files
are never rewritten or shadowed; move that configuration to `opencode.json`
before running the installer. Loom does not create or modify Markdown files.

## Codex

Install or verify the global Codex MCP registration from the connected
repository:

```bash
loom install codex
```

The installer also merges conversation hooks into `.codex/hooks.json`. Codex
asks you to review and trust project hooks before they run. The MCP process
selects the nearest `.loom/project.json`, reads its matching
credential from `~/.loom/projects.json`, and records writes as `codex_cli` with
a process-level session ID. `LOOM_API_URL`, `LOOM_PROJECT_ID`, and
`LOOM_API_KEY` remain compatibility overrides for controlled CI environments.
The installer does not create or modify Markdown files.

If a different MCP server already uses the name `loom`, the installer leaves it
unchanged and prints the explicit removal and reinstall commands.

## Terminal conversation capture

`loom install codex|claude|opencode|all` installs repository-local capture
alongside MCP access. A valid `.loom/project.json` binding is required. Loom
captures submitted user text and final assistant text from root sessions;
commands, tool results, reasoning, attachments, and subagent messages are not
uploaded. Claude Code uses `.claude/settings.json` hooks. Unrelated harness
configuration is preserved.
Capture requires Codex 0.160.0+, Claude Code 2.1.206+, or OpenCode 1.18.34+.
The same installer adds prompt hooks that deliver a cited brief and original
matching history before each submitted prompt, including follow-ups. Rerun
`loom install all` once in repositories installed before this feature; MCP
registration alone cannot activate automatic prompt delivery. If Loom is
unavailable, the prompt proceeds without added context.

Capture writes to a user-only SQLite queue at `~/.loom/capture.db` before
uploading. If the API is offline, later events retry automatically. Pause
capture before entering sensitive text; pausing does not delete stored messages.

```bash
loom capture status
loom capture pause
loom capture resume
loom capture flush
loom capture import codex             # preview only
loom capture import opencode --apply  # explicit historical import
loom capture import all --session <native-session-id> --apply
```

Historical import filters sessions to the bound repository and sends only
textual user and final assistant messages. Codex and Claude transcript parsing
is best effort because those formats may change. `loom capture status` prints
queue counts and delivery errors without message text or credentials.

## Inspect project memory

The inspection commands are read-only and use the project selected by the
nearest `.loom/project.json`:

```bash
loom status
loom links
loom history --limit 20
loom history --source opencode --session <session-id> --type task_result

# Inspect the cited bundle delivered for a submitted coding prompt
loom context "How should login tokens expire?" --rich
```

Each command also supports `--json`. `loom links` shows linked browser chats
and harness sessions observed in stored provenance. An observed session is
historical activity, not an indication that the agent process is currently
online. Loom commands do not create or modify Markdown instruction files.

MCP clients can inspect the same information with `list_recent_context` and
`list_sources`. Recent units include full IDs and parent citations for durable
handoffs.

### Dashboard source explorer

Open the hosted dashboard and select a project to inspect all memory sources in
one timeline. Browser conversations are grouped by URL; coding-harness activity
is grouped by source, observed session ID, and agent. "Observed session" means
stored historical activity, not a currently running process.

The dashboard can filter the complete project history by source, text, context
type, agent, and date. Each unit retains its full ID, source, session, agent,
timestamp, source URL, and parent IDs. Structured task results show the task
name, files touched, test outcomes, errors, blockers, next steps, and confidence
without requiring raw JSON. The explorer is intentionally read-only: it does
not unlink, delete, resync, or manually write context.
Terminal sessions show user and assistant turns in occurrence order with their
harness, title, session, agent, and parent links. Captured prompts are also
available to `loom context` and MCP `read_context`.

## End-to-end test flow

Use this sequence to verify the complete product rather than isolated screens:

1. Start PostgreSQL/Redis, apply migrations, and start Uvicorn with
   `uvicorn loom.api.main:app --host 0.0.0.0 --port 8000`.
2. Configure Google OAuth as described below, then run `loom login`.
3. Run `loom init "E2E Test" --install all`, then verify the CLI is connected:

   ```bash
   loom config
   ```

4. Install the extension, use **Continue with Google** with the same account,
   select `E2E Test`, and link a supported AI conversation.
5. Send a unique message in the chat, such as
   `LOOM_E2E_2026: the retry policy is exponential backoff`.
6. Wait for the popup to say **All captured messages are synced**.
7. Verify browser-to-terminal retrieval:

   ```bash
   loom context "LOOM_E2E_2026 retry policy" --scope full --json
   ```

8. Open the dashboard from the popup. Confirm the linked chat appears under
   browser conversations and that its timeline shows the source URL, full unit
   ID, provenance, and new message.
9. Start OpenCode and ask it to continue the retry-policy work. Confirm it
   reads the browser context and writes a structured result with OpenCode source
   and session provenance.
10. Start Codex and retrieve the OpenCode handoff, then inspect it with
    `loom history --source opencode` and `loom links`. In the dashboard, select
    the OpenCode observed session and confirm its structured task result, tests,
    parent IDs, and next steps are readable.
11. When Claude Code access is available, optionally repeat the handoff through
    Claude and confirm its source and session remain independently traceable.

## Automated verification

With PostgreSQL and Redis running and migrations applied:

```bash
ruff check .
mypy loom
pytest -q
node --check extension/config.js
node --check extension/shared.js
node --check extension/storage.js
node --check extension/background.js
node --check extension/content.js
node --check extension/popup.js
node --test tests/extension/*.js
python -m json.tool extension/manifest.json >/dev/null
docker build -t loom-api:local -f infra/Dockerfile .
```

Useful focused checks:

```bash
pytest -q tests/unit
pytest -q tests/integration/test_cli.py tests/integration/test_mcp_server.py
./scripts/health-check.sh
```

## Configuration

The complete local template is [.env.example](.env.example). Important values:

- `DATABASE_URL`, `REDIS_URL` — required infrastructure
- `CORS_ALLOWED_ORIGINS` — comma-separated browser-origin allowlist; defaults
  to the configured frontend origin
- `EMBEDDING_PROVIDER` — `stub`, `openai`, or `local`
- `OPENAI_API_KEY` — required only for OpenAI embeddings
- `SUMMARIZATION_PROVIDER` — `auto`, `gemini`, `xai`, `groq`, or `stub`; `auto`
  selects Gemini first when `GEMINI_API_KEY` is set
- `GEMINI_API_KEY` — required for Gemini summarization
- `GROQ_API_KEY` — required for Groq summarization/agent calls
- `BOOTSTRAP_TOKEN` — required on a non-development server
- `ALLOW_LEGACY_UUID_TOKENS` — temporary upgrade compatibility; keep `false`
- `ALLOW_AGENT_KEY_ENROLLMENT` — legacy project-key credential minting; keep
  `false` in public production so only account members can provision keys
- `PUBLIC_ACCOUNT_CREATION_ENABLED` — allows first-time Google login to create an account
- `EMAIL_PASSWORD_AUTH_ENABLED` — local/dev migration fallback; keep `false`
  in the public deployment
- `GOOGLE_OAUTH_ENABLED` — enables verified Google identity exchange
- `GOOGLE_CLI_CLIENT_ID` — Google **Desktop app** OAuth client used by CLI PKCE
- `GOOGLE_CLI_CLIENT_SECRET` — optional desktop client secret
- `GOOGLE_EXTENSION_CLIENT_ID` — Google **Chrome Extension** OAuth client
- `GOOGLE_WEB_CLIENT_ID` — Google **Web application** client for the dashboard
- `USER_SESSION_TTL_DAYS` — absolute lifetime of revocable account sessions
- `AGENT_KEY_TTL_DAYS` — lifetime of newly issued CLI/extension credentials
- `AUTH_RATE_LIMIT_ATTEMPTS`, `AUTH_RATE_LIMIT_WINDOW_SECONDS` — Redis-backed
  auth abuse limits

The local `sentence-transformers` provider is intentionally optional because
its PyTorch runtime is large. Install it only on workers that use it:

```bash
pip install ".[local-embeddings]"
```

For production, keep a long random `BOOTSTRAP_TOKEN` as an operator recovery
credential. Public users never receive or need it. It is not a project API key.

### Configure Google OAuth

Create one Google Cloud project, configure its OAuth consent screen, and create
three OAuth clients in **Google Cloud Console → APIs & Services →
Credentials**:

1. **Desktop app** — set its client ID as `GOOGLE_CLI_CLIENT_ID`. The CLI uses
   Authorization Code with PKCE and a temporary `127.0.0.1` callback.
2. **Chrome Extension** — create it for Loom's stable extension ID
   `cdahjeahjonafooajjbccipeaoefdjgm`, then set the client ID as
   `GOOGLE_EXTENSION_CLIENT_ID`.
3. **Web application** — add the deployed API origin, such as
   `https://loom-api-zzy0.onrender.com`, to **Authorized JavaScript origins**
   and set its client ID as `GOOGLE_WEB_CLIENT_ID`.

For a Google app still in testing mode, add each tester under **OAuth consent
screen → Test users**. Set all three IDs on Render before deploying with
`GOOGLE_OAUTH_ENABLED=true`. Do not put OAuth client IDs into project `.env`
files; they are server configuration and are intentionally public identifiers.

## Deployment

The MVP deployment target is Render because it can run this FastAPI service,
PostgreSQL, and Redis-compatible Key Value on free plans. Free Render services
are good for demos and early testing, not durable production: the API spins
down when idle, the free database expires after 30 days, and free Key Value is
in-memory only.

The repository includes [render.yaml](render.yaml), which provisions:

- `loom-api` — Dockerized FastAPI web service
- `loom-postgres` — PostgreSQL 16 database
- `loom-redis` — Redis-compatible Key Value instance

The API container runs `python -m loom.api.start`, which applies pending SQL
migrations and then starts Uvicorn on Render's injected `PORT`.

### Deploy on Render

1. Push this repository to GitHub.
2. Open Render and choose **New > Blueprint**.
3. Connect the GitHub repo and select `render.yaml`.
4. Create the blueprint and wait for `loom-api`, `loom-postgres`, and
   `loom-redis` to finish provisioning.
5. Open the `loom-api` service and copy its public URL, for example:

   ```bash
   https://loom-api.onrender.com
   ```

6. Verify the deployed API:

   ```bash
   export LOOM_API_URL="https://<your-render-service>.onrender.com"
   curl "$LOOM_API_URL/health"
   curl "$LOOM_API_URL/ready"
   ```

`/health` should return `{"status":"ok"}`. `/ready` should return database and
Redis status as `ok`.

### Create a hosted account and project

Open the deployed API URL in a browser to use the account dashboard, or run:

```bash
export LOOM_API_URL="https://<your-render-service>.onrender.com"
loom login
loom init "Loom MVP" --install all
```

Google login creates or reuses the account without creating a project. Init
creates the project and stores the local-agent key privately under `~/.loom`.
The Render `BOOTSTRAP_TOKEN` is needed only for the explicit operator command
`loom init --bootstrap`.

### Point the extension at the hosted API

Install or refresh the unpacked extension for the hosted deployment:

```bash
loom extension install --api-url "$LOOM_API_URL" --force
loom extension status --check-api
loom extension path
```

Then:

1. Open or reload the directory printed by `loom extension path` in
   `chrome://extensions`.
2. Continue with the same Google account used by the CLI, select the
   automatically discovered project, and link the chat. No project ID or API
   key copying is required.

### Hosted smoke test

```bash
export CHAT_URL="https://claude.ai/chat/<chat-id>"

curl -sS -X POST \
  "$LOOM_API_URL/v1/projects/$LOOM_PROJECT_ID/link/chat" \
  -H "Authorization: Bearer $LOOM_API_KEY" \
  -H "Content-Type: application/json" \
  --data "{\"chat_url\":\"$CHAT_URL\",\"title\":\"Claude conversation\",\"platform\":\"claude.ai\"}"

loom context "hosted Loom MVP smoke test" --scope full
```

Open the public account dashboard at:

```bash
open "$LOOM_API_URL/"
```

You should see the linked chat and the terminal-written decision in the same
project history.

### Production topology

After setting production service URLs and secrets in `.env`, the vendor-neutral
runtime topology can be started with:

```bash
docker compose -f infra/compose.production.yml up -d --build
```

The container runs as an unprivileged `loom` user. The API readiness probe does
not become healthy until both PostgreSQL and Redis respond.

For a paid always-on production deployment, add separate worker services that
run:

```bash
python -m loom.services.retrieval.embedding_worker
python -m loom.services.retrieval.summarizer
```

The free Render MVP can still capture, store, retrieve, and display context;
workers improve vector search and periodic summary freshness.

The included GitHub workflow validates that the production image builds. It
does not deploy to a vendor because this repository does not define a target
cloud account, database, Redis service, domain, or secret store. Configure
those platform-specific resources before calling any deployment production.

## Architecture map

```text
Browser AI chat ── Chrome extension ──┐
                                      ├─ FastAPI ─ PostgreSQL/pgvector
Claude Code ───────── MCP ────────────┤      │
OpenCode ──────────── MCP ────────────┤      └─ Redis workers/presence
Codex ─────────────── MCP ────────────┘                  │
                                                Project dashboard
```

Context writes are idempotent, project-authorized, and recorded in an
append-only event log. Browser content remains external-trust context; agent and
user decisions retain their distinct trust tiers.

## License

MIT
