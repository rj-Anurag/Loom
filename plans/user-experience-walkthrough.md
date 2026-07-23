# Loom — User Experience Walkthrough

## Layer 1: What You Install

```
Your Machine
├── loom/                    # You clone this repo
├── .venv/                   # Python venv (one-time)
├── docker compose up        # Postgres + Redis (one command)
├── loom serve               # Loom context server (background daemon)
└── browser extension        # Bridges AI chats into Loom
```

**You run 3 things:**
1. Install the **Loom Browser Extension** — bridges browser AI chats into Loom
2. `docker compose up` — starts Postgres + Redis
3. `loom serve` — starts the Loom context server (runs in background)

Once these are running, Loom integrates into your existing AI CLI tools (Claude Code, opencode, etc.) as an **MCP tool** or **plugin**.

---

## Layer 2: What It Looks Like In Practice

You never open a Loom dashboard. You stay in your existing CLI tool.

```
$ claude                          ← You open Claude Code as usual
╭──────────────────────────────────────────────────╮
│  Claude Code                                    │
│                                                  │
│  You: /loom build login feature                 │
│       ──────────────────────────────             │
│       Loom detected:                             │
│         📄 3 browser chats about "auth"          │
│         📄 Previous context: "db schema design"  │
│         📄 2 agent sessions from yesterday       │
│       Injected into context.                     │
│       ──────────────────────────────             │
│                                                  │
│  Claude: I see you discussed email+password      │
│  auth with JWT and bcrypt in your browser        │
│  chat. Let me implement that...                  │
╰──────────────────────────────────────────────────╯
```

Or as a mention (`@loom`) in the prompt itself:

```
$ claude                                              
> @loom implement the login feature we discussed yesterday

(Loom silently gathers context from browser chats, 
 previous agent runs, and local files — injects it 
 into the prompt before Claude processes it)

Claude: Based on your auth architecture chat and
the DB schema from yesterday's session, here's
the implementation...
```

**The key insight:** The user writes their normal prompt. Loom is a **pre-processing layer** — it intercepts the prompt, gathers relevant context from everywhere, augments the prompt with it, then hands it to the AI.

---

## Layer 3: The Full User Flow

Here's a concrete scenario — you're building a login feature:

### STEP 0: You design architecture in a browser chat
- Open Claude.ai, start a chat: "Design auth for my app"
- Discuss: "Use email + password + JWT. We'll use bcrypt for hashing."
- The Loom extension detects a new chat → one-tap prompt appears
- You tap "Link to project: loom-auth" → done
- Every message from that chat syncs into Loom's context store

### STEP 1: You open your CLI and write a prompt
- Open Claude Code in your terminal
- Type: `@loom implement the login feature`
- You don't paste any context — just the intent

### STEP 2: Loom gathers context automatically
```
Your prompt: "@loom implement the login feature"

           │
           ▼
    ┌──────────────┐
    │   Loom MCP   │
    │   Tool/Hook  │
    └───┬───┬───┬──┘
        │   │   │
   ┌────┘   │   └────┐
   ▼        ▼        ▼
Browser  Previous  Local
Chats    Agent     Files
         Sessions
```

**What Loom retrieves:**
| Source | Context Found |
|---|---|
| Browser (Claude.ai) | "Use email + password + JWT. bcrypt for hashing." |
| Previous agent session | DB schema for users table (created yesterday) |
| Local files | Existing project structure and dependencies |

### STEP 3: Loom augments your prompt
```
Before Loom:   "implement the login feature"

After Loom:    "implement the login feature
               
               [Context from browser chat — Claude.ai, 2h ago]
               User discussed: email + password + JWT auth
               Decision: use bcrypt for password hashing
               User said: "We'll keep it simple, no OAuth yet"
               
               [Context from agent session — yesterday]
               Agent created: users table schema
               Columns: id, email, password_hash, created_at
               
               [Context from local files]
               Project: FastAPI + SQLAlchemy + asyncpg
               Existing: users.py model file found]"
```

### STEP 4: The AI responds with full awareness
- Claude sees your architecture decisions without you re-explaining them
- It knows the DB schema from yesterday's session
- It understands the project structure from local files
- Result: accurate, context-aware code in one shot

### STEP 5: The result is saved back
- The code Claude writes is saved as a new context unit
- Future `@loom` prompts will include this session's work
- Other team members using Loom can see what was built

---

## Layer 4: The Core Loop

```
┌─────────────────────────────────────────────────────────┐
│                  THE CORE LOOP                           │
│                                                         │
│  User writes prompt with @loom or /loom                 │
│  1. Loom intercepts the prompt                          │
│  2. read_context("login feature")                       │
│     - Searches browser chats, agent sessions, files     │
│     - Ranks by relevance + recency                      │
│     - Returns top-N context units within token budget   │
│  3. Augments the original prompt with context           │
│  4. Passes augmented prompt to the AI model             │
│  5. AI responds with full context awareness             │
│  6. AI's response is saved as a new context unit        │
│  7. Embedding is computed asynchronously                │
│  8. Next @loom prompt will include this response        │
│                                                         │
│  This loop runs for EVERY prompt with @loom.            │
│  EVERYTHING is recorded. NOTHING is lost.               │
└─────────────────────────────────────────────────────────┘
```

The guarantee: Every single thing any agent or user does is:
1. Recorded in the event log (immutable, append-only)
2. Available for future prompts to reference
3. Never deleted (only summarized/compressed)

---

## Layer 5: The Three Guarantees

| What | Why It Matters to You |
|---|---|
| **Never lost** | Every decision, every message, every result is in the event log. You can always go back and see why something was done. |
| **Context-aware** | Every prompt has full context — from browser chats, past agent runs, and local files — automatically. You never re-explain. |
| **Provenance** | Every piece of context is tagged with its source (browser, user, agent, file) and when it was created. You always know where it came from. |

---

## Summary: What You Actually Do

| You want to... | What you do |
|---|---|
| **Save context from a browser AI chat** | Install extension → one-tap link → auto-synced |
| **Work with full context in your CLI** | Type `@loom <your prompt>` — context is injected automatically |
| **See what context was gathered** | Loom prints "Detected: 3 browser chats, 2 agent sessions" before the AI responds |
| **Build on yesterday's work** | Just mention it — Loom finds the relevant sessions automatically |
| **Share context with a team member** | They install Loom → same project → same context store |
