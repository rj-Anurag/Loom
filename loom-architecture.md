# Loom — System Architecture Document

**Project:** Loom — a multi-agent system where agents (local, cloud, browser-chat) collaborate on shared projects via a memory-efficient, never-lost shared context layer.
**Author role:** Senior Staff Architect review
**Status:** v1 design, pre-implementation

---

## 1. Executive Summary

Loom lets multiple AI agents — running on a developer's machine, in the cloud, or inside a browser chat session — collaborate on the same project while seeing a single, consistent, evolving context. The system's defining bet is that **context should never be lost, only compressed or deferred**, and that memory efficiency (what gets loaded into an agent's window, when) is the hard problem worth solving well, not an afterthought.

**Primary objectives:**
- Give any agent, regardless of where it runs, access to the same up-to-date project context
- Guarantee no information written by any agent is ever silently dropped
- Keep per-agent token usage low by surfacing only what's relevant to the current task
- Support many agents working concurrently without corrupting shared state

**Core challenges the architecture must solve:**
1. **The retrieval problem** — deciding what subset of a potentially unbounded history to hand an agent right now
2. **The concurrency problem** — multiple agents writing to shared context at once without conflicts silently resolving as "last write wins"
3. **The durability problem** — architecturally guaranteeing nothing is deleted or unreachable, even under aggressive summarization
4. **The heterogeneity problem** — local, cloud, and browser agents have different latency, connectivity, and trust characteristics but must share one source of truth

---

## 2. Requirements Analysis

### Functional Requirements
- Agents can read the current shared context relevant to their task
- Agents can write new context (decisions, artifacts, task results, messages) without overwriting others' work
- Users can observe agent activity live in a browser chat interface
- The system supports many agents working on the same project concurrently
- Historical context is always retrievable — nothing is truly deleted
- New agents (local, cloud, or browser) can join an in-progress project and get caught up efficiently
- Users can inspect *why* an agent made a decision (provenance/audit trail)

**Key workflows:**
1. Agent starts a task → requests relevant context → does work → writes result back
2. Two agents work on related subtasks concurrently → their outputs merge into shared context
3. User opens browser chat mid-project → sees live state and history
4. Context grows over time → system compresses/summarizes for efficient injection without deleting originals

### Non-Functional Requirements

| Category | Requirement |
|---|---|
| Scalability | Support dozens of concurrent agents per project at v1; architecture should not block scaling to hundreds |
| Performance | Context retrieval for a single agent turn should resolve in low hundreds of ms, not seconds |
| Reliability | No data loss on write; graceful degradation if the LLM API or vector store is briefly unavailable |
| Security | Agents authenticate individually; no agent can read/write outside its authorized project scope |
| Availability | Target 99.5% for v1 (single-region); revisit for multi-region later |
| Compliance | No hard compliance requirement at v1 (no PII/regulated data assumed); design should not preclude adding it later |
| Cost | Token costs dominate; storage and compute should stay a small fraction of LLM API spend |

---

## 3. System Context

**Actors:**
- **Human user** — initiates projects, observes/steers agents via browser chat, approves sensitive actions
- **Local agent** — runs on the developer's machine (e.g., via Claude Code), has file-system access
- **Cloud agent** — runs as a hosted process, no local file access, calls APIs/MCP tools
- **Browser-chat agent** — lightweight, session-scoped, primarily conversational

**External systems:**
- Anthropic API (Messages endpoint, tool use)
- MCP-exposed tools (whatever each agent is connected to — file systems, git, external services)
- Object storage (for artifacts agents produce: files, diffs, generated assets)

**System boundaries:** Loom itself owns the *shared context store*, the *coordination/merge logic*, and the *retrieval layer*. It does not own the LLM inference (delegated to the Anthropic API) or agent-specific tool execution (delegated to MCP servers each agent connects to).

**Component interaction, at a glance:**

```
[User] <-> [Browser Chat UI] <-> [Loom API Gateway]
                                        |
        -------------------------------------------------------
        |                    |                    |
  [Local Agent]        [Cloud Agent]        [Browser Agent]
        |                    |                    |
        --------------- MCP: read_context/write_context ---------------
                                        |
                            [Loom Context Service]
                                        |
                -----------------------------------------------
                |                       |                     |
        [Postgres + pgvector]      [Redis]              [Object Storage]
        (context graph + search)  (locks, live state)   (artifacts)
```

---

## 4. High-Level Architecture

**Selected style: Modular Monolith (v1) with an Event-Driven core, evolving toward Microservices at scale.**

Rationale:
- A small number of well-defined modules (Context Service, Coordination/Merge Service, Retrieval Service, Gateway) don't yet need independent deployment or scaling in v1 — splitting them prematurely adds operational overhead without benefit.
- The **event-driven core** (an append-only event log of context writes) is non-negotiable from day one: it's what makes "nothing is ever lost" an architectural guarantee rather than a policy. Every write is an event; current state is a projection over events.
- As load grows, the Retrieval Service (CPU/IO heavy — embeddings, hybrid search) and the Coordination Service (needs low-latency locking) are the natural first candidates to split into independent services, since they have different scaling profiles from the rest.

**Rejected alternatives:**
- **Full microservices from day one** — rejected: premature for a single-team, pre-product-market-fit project; the coordination overhead (service discovery, distributed tracing, network calls for every context read) would slow iteration without a load profile that justifies it.
- **Pure serverless (functions-per-agent-turn)** — rejected: agent turns need low-latency access to a stateful context store and locks; cold starts and statelessness fight against exactly the coordination guarantees the project depends on. Serverless remains a good fit for stateless pieces (e.g., embedding generation batch jobs), and is used there.
- **Pure event sourcing with no read-optimized store** — rejected: replaying the full event log for every context read would be too slow; hence current-state projections (Postgres tables, embedding index) are maintained alongside the immutable event log.

---

## 5. Core Components

### API Gateway
- **Responsibilities:** authn/session handling, request routing to the Context Service, rate limiting, WebSocket connections for live browser updates
- **Inputs:** HTTP/WebSocket requests from agents and the browser UI
- **Outputs:** routed requests, live event broadcasts
- **Dependencies:** Auth service, Context Service
- **Failure scenarios:** gateway down → agents queue writes locally (local agent) or fail fast with retry (cloud/browser agents); browser UI shows "reconnecting"

### Context Service
- **Responsibilities:** owns the "Context Unit" data model (see §7), accepts writes, appends to the event log, updates projections
- **Inputs:** write_context / read_context calls (via MCP), event log
- **Outputs:** Context Units, updated graph edges, retrieval-ready projections
- **Dependencies:** Postgres, Redis (for locks), Coordination Service
- **Failure scenarios:** write fails mid-transaction → event log is the source of truth, projections rebuilt from log; partial writes never surface as "committed" to other agents

### Coordination Service
- **Responsibilities:** branch/merge logic for concurrent writes, conflict detection, task assignment (hybrid centralized/decentralized — see §13)
- **Inputs:** write intents from multiple agents
- **Outputs:** merge decisions, conflict flags for human/agent resolution
- **Dependencies:** Redis (short-lived locks), Context Service (event log)
- **Failure scenarios:** lock service down → writes fall back to optimistic concurrency with version checks, conflicts surfaced rather than silently dropped

### Retrieval Service
- **Responsibilities:** embedding generation, hybrid (vector + keyword) search, hierarchical summarization for context assembly
- **Inputs:** read_context queries (task description, agent scope)
- **Outputs:** ranked, budget-aware context bundles sized to the requesting agent's token budget
- **Dependencies:** Postgres + pgvector, embedding model
- **Failure scenarios:** embedding service down → falls back to keyword-only search with a degraded-mode flag

### Agent Services (Local / Cloud / Browser)
- **Responsibilities:** run the actual LLM turn, call MCP tools including Loom's own read/write_context
- **Inputs:** task from user or Coordination Service, retrieved context
- **Outputs:** context writes, artifacts, messages
- **Dependencies:** Anthropic API, Loom MCP server, project-specific tools
- **Failure scenarios:** agent crashes mid-task → partial work already written is preserved as a Context Unit; task marked incomplete, resumable by any agent

### LLM Layer
- Anthropic API (Messages endpoint), called by each Agent Service, not by the Context/Coordination services directly — keeps inference concerns isolated from storage/coordination concerns

### Databases
- **Postgres + pgvector** — Context Units, graph edges, embeddings, hybrid search
- **Redis** — locks, live agent presence/status, ephemeral session state

### Object Storage
- Artifacts too large or binary for the context store (files, generated assets), referenced by Context Units via pointer, not inlined

### Authentication Service
- Issues per-agent credentials scoped to a project; browser sessions use standard user auth

### Monitoring Stack
- See §12

---

## 6. Data Flow Design

### Workflow: Agent completes a subtask and writes back

1. Agent calls `read_context(task_description, token_budget)` via MCP
2. Retrieval Service embeds the task description, runs hybrid search against Postgres+pgvector scoped to the project, ranks and packs results into the token budget, returns a context bundle
3. Agent performs its task using the LLM, produces a result (text, artifact, decision)
4. Agent calls `write_context(content, parent_ids, type)` via MCP
5. Coordination Service checks for conflicting concurrent writes touching the same parent Context Units (via version check); if clean, proceeds
6. Context Service appends an immutable event to the event log, updates the Postgres projection (new Context Unit row, new graph edges), triggers async embedding of the new content
7. API Gateway broadcasts the update over WebSocket to any connected browser sessions watching the project
8. **Failure handling:** if step 5 detects a conflict, the write is held as a "pending branch" and flagged for merge (auto-merge if non-overlapping, human/agent review if overlapping) — never silently dropped or silently overwritten
9. **Retry strategy:** writes are idempotent by client-generated UUID; agent retries a failed write safely without duplicating the Context Unit

### Workflow: New agent joins an in-progress project

1. Agent authenticates, requests project context via `read_context(scope="onboarding")`
2. Retrieval Service returns the hierarchical summary (top-level project state) plus pointers into the full graph for drill-down
3. Agent can issue follow-up `read_context` calls scoped to specific subtasks as needed, rather than loading full history upfront

---

## 7. Database Design

### Why Postgres + pgvector (not a dedicated graph DB, not a dedicated vector DB)
For v1, a single well-understood datastore reduces operational surface area. Postgres handles relational integrity (foreign keys model the context graph's edges) and pgvector handles embedding search in the same transaction boundary as writes — avoiding a separate consistency problem between "the graph" and "the search index." Revisit a dedicated graph DB (Neo4j) if graph traversal patterns outgrow adjacency-list queries.

### Core schema (simplified)

```
context_units
  id                UUID PK
  project_id        UUID
  agent_id          UUID
  type              ENUM (message, decision, artifact_ref, task_result, summary)
  content           TEXT
  embedding         VECTOR(1536)
  created_at        TIMESTAMP
  version           INT          -- optimistic concurrency
  branch_id         UUID         -- for git-style branching

context_edges
  parent_id         UUID FK -> context_units.id
  child_id          UUID FK -> context_units.id
  relation          ENUM (derived_from, supersedes, references, merged_from)

event_log
  id                UUID PK
  project_id        UUID
  event_type        ENUM (write, merge, conflict_flagged)
  payload           JSONB
  created_at        TIMESTAMP     -- append-only, immutable, source of truth

agents
  id, project_id, kind (local/cloud/browser), credentials_ref

projects
  id, name, created_at, retention_policy
```

### Entity relationships
- `context_units` form a DAG via `context_edges` (not a strict tree — a unit can derive from multiple parents, e.g. a merge)
- `event_log` is the immutable ledger; `context_units`/`context_edges` are a queryable projection rebuildable from it

### Indexing strategy
- IVFFlat or HNSW index on `embedding` for approximate nearest-neighbor search
- B-tree on `(project_id, created_at)` for chronological scoping
- GIN index on `content` for keyword/full-text search (hybrid search)

### Partitioning strategy
- Partition `context_units` and `event_log` by `project_id` range/hash once project count grows — keeps per-project queries fast and allows archiving cold projects independently

### Read/write patterns
- Writes: moderate frequency, one per agent action, must be transactionally safe
- Reads: high frequency, latency-sensitive, mostly scoped to a single project and a relevance window — good fit for the above indexes

### Data retention strategy
- **Nothing is hard-deleted.** "Compression" produces new `summary`-type Context Units that reference (not replace) the originals via `supersedes` edges. Originals remain queryable; retrieval simply prefers summaries by default and falls back to originals on demand. Retention policy per project can archive (not delete) old event log segments to cold storage.

---

## 8. API Design

**Architecture:** gRPC internally (Context/Coordination/Retrieval services talk to each other with low overhead), REST at the Gateway for browser/external simplicity, MCP as the agent-facing tool interface layer.

Rationale: agents already speak MCP naturally (tool calls); the browser UI is simplest over REST/WebSocket; internal service-to-service calls benefit from gRPC's performance and strong typing. GraphQL was considered for the browser API but rejected — the UI's query patterns are simple enough (project state, live updates) that GraphQL's flexibility isn't worth its complexity here.

**Endpoint structure (REST, Gateway-facing):**
- `POST /projects/{id}/context` — write
- `GET /projects/{id}/context?query=...&budget=...` — retrieval
- `GET /projects/{id}/events` (WebSocket) — live updates
- `POST /projects/{id}/agents` — register an agent session

**MCP tools (agent-facing):** `read_context`, `write_context`, `get_project_summary`

**Authentication model:** per-agent API keys scoped to a project; browser sessions use standard session/JWT auth; all requests carry `project_id` + `agent_id` for scoping checks

**Versioning strategy:** URL-path versioning (`/v1/...`) for the REST API; MCP tool schemas versioned via a `schema_version` field so older agents degrade gracefully rather than breaking

**Rate limiting:** per-agent token bucket at the Gateway, generous for read (retrieval is cheap to serve, expensive to skip) and stricter for write (writes are the scarce, conflict-prone resource)

---

## 9. Scalability Design

- **Horizontal scaling:** Gateway and Agent Services are stateless — scale by adding instances behind a load balancer. Context/Coordination/Retrieval services scale horizontally behind gRPC load balancing once split out of the monolith.
- **Load balancing:** standard L7 load balancer in front of the Gateway; sticky sessions for WebSocket connections
- **Auto-scaling:** scale Agent Service instances on queue depth (pending tasks); scale Retrieval Service on read latency/CPU (embedding generation is the hot path)
- **Database scaling:** read replicas for Postgres once read volume outgrows a single primary; partitioning (see §7) before considering sharding
- **Cache strategy:** Redis caches hot retrieval results (recent queries per project) and hierarchical summaries to avoid recomputing on every onboarding read
- **Queue strategy:** an event queue (e.g., a lightweight message broker) decouples the write path from downstream projection updates and embedding generation, so a slow embedding job never blocks a write from being acknowledged

**Expected bottlenecks:**
1. Embedding generation under high write volume → mitigate with async embedding + queue, not synchronous-with-write
2. Lock contention during high-concurrency merges on the same subtree → mitigate with fine-grained locks scoped to individual Context Units, not project-wide locks
3. Vector index rebuild cost as data grows → mitigate with incremental index structures (HNSW) over full rebuilds

---

## 10. Security Architecture

- **Authentication:** per-agent scoped API keys; browser sessions via standard session/JWT
- **Authorization:** every read/write checked against `project_id` + agent's granted scope; no agent can address another project's context
- **Secrets management:** API keys and credentials in a managed secrets store (e.g., cloud provider's secrets manager), never in Context Units or logs
- **Encryption at rest:** database and object storage encryption enabled by default
- **Encryption in transit:** TLS everywhere, including internal gRPC
- **API security:** input validation on all write payloads, strict schema validation on MCP tool calls
- **OWASP considerations:** standard injection/auth/misconfig checks applied to the Gateway and REST surface
- **Agent and LLM security risks:**
  - **Prompt injection:** content retrieved from the shared context store is untrusted input to any agent reading it — the Retrieval Service should tag content provenance (which agent wrote it) so consuming agents can weight/verify instructions embedded in retrieved context rather than blindly executing them
  - **Data leakage prevention:** cross-project isolation enforced at the query layer (every retrieval query is hard-scoped to `project_id`); no agent's context is retrievable outside its project even by accident of a bad query
  - Sensitive artifacts (credentials, secrets) should never be written into Context Units as plain content — enforce a content-scanning check on write for common secret patterns

---

## 11. Reliability & Resilience

- **High availability:** multi-instance deployment of stateless services; Postgres with a standby replica for failover
- **Disaster recovery:** event log is the durable source of truth — projections (Postgres tables, vector index) can be fully rebuilt from it if corrupted
- **Backup strategy:** continuous WAL archiving for Postgres, periodic snapshots of object storage
- **Circuit breakers:** Agent Services trip a circuit breaker on repeated Context Service failures, falling back to degraded mode (agent works from its own local scratch context, flags for later reconciliation) rather than blocking entirely
- **Retries:** idempotent writes (client-generated UUIDs) make retries safe by default
- **Dead-letter queues:** failed async jobs (embedding generation, projection updates) land in a DLQ for inspection/replay rather than silently dropping
- **Graceful degradation:** if the Retrieval Service is down, agents can still write (preserving "never lost") even though reads are temporarily degraded to raw chronological context instead of ranked retrieval

---

## 12. Observability

- **Logging:** structured logs per service, correlated by a `trace_id` that follows a request from Gateway through Context/Coordination/Retrieval
- **Monitoring:** standard service metrics (latency, error rate, saturation) per component
- **Distributed tracing:** trace every agent turn end-to-end (read_context → LLM call → write_context) to diagnose slow or failed turns
- **Metrics:** context write conflict rate, retrieval latency, token budget utilization per agent turn, event log growth rate
- **Alerting:** conflict rate spikes, embedding queue backlog growth, write failure rate, Postgres replication lag
- **Incident response:** runbooks tied to each alert; conflict-rate spikes point at Coordination Service, latency spikes point at Retrieval Service

---

## 13. Agentic AI Architecture

This is the heart of the project, so decisions here are made explicitly rather than left open.

- **Agent orchestration model: Hybrid.** A thin **centralized Coordination Service** handles task assignment and conflict arbitration (this is a small, well-scoped responsibility, not a heavyweight controller), while agents **read/write the shared context store directly and decentrally** otherwise. This avoids both extremes: pure decentralization risks silent conflicts at scale; pure centralization turns the controller into a bottleneck and single point of failure for every context access.
- **Agent communication model:** agents do not talk to each other directly — all communication is mediated through the shared context store (an agent "speaks" by writing a Context Unit; another agent "hears" by retrieving it). This keeps communication auditable and replayable.
- **Memory architecture:** three-tier, matching §2's memory-type distinction:
  - *Working memory* — the token-budgeted bundle assembled per-turn by the Retrieval Service
  - *Episodic memory* — the full event log + Context Unit graph, always retrievable
  - *Semantic memory* — periodically distilled summary Context Units (project-level facts, standing decisions) that get preferentially surfaced
- **Context management:** "never lost" means the event log and DAG are append-only and immutable; efficiency comes from retrieval ranking and summarization, never deletion.
- **Tool invocation strategy:** `read_context`/`write_context` as MCP tools, callable by any agent regardless of runtime location (local/cloud/browser) — the interface is uniform even though the underlying agent process differs
- **Planning and execution flow:** Coordination Service assigns/accepts a task → agent retrieves context → agent plans and executes (its own LLM loop, opaque to Loom) → agent writes results → Coordination Service checks for conflicts and updates task state
- **Human-in-the-loop design:** conflicts that can't be auto-merged (overlapping edits to the same Context Unit) are surfaced to the user via the browser UI for resolution, rather than resolved silently by heuristic
- **Multi-agent coordination patterns:** git-style branch/merge for concurrent context writes (Omnigraph-inspired) — each agent's in-progress work is a branch off the current context graph; merges are automatic when non-overlapping, flagged for review when not

---

## 14. Infrastructure Architecture

- **Cloud architecture:** single-region for v1 (matches the 99.5% availability target); revisit multi-region once the user base or compliance needs demand it
- **Networking:** private VPC for Postgres/Redis; Gateway is the only public-facing surface; internal service mesh for gRPC traffic
- **Containerization:** each service (Gateway, Context, Coordination, Retrieval) as its own container image, even while co-deployed as a modular monolith initially — this makes the later split into microservices a deployment change, not a rewrite
- **Orchestration platform:** Kubernetes (or a managed equivalent) for scaling and self-healing
- **CI/CD pipeline:** standard build → test → deploy pipeline; database migrations gated behind review given the schema's centrality to the whole system
- **Environment strategy:** Development (local docker-compose, local agents only), Staging (full cloud stack, synthetic multi-agent load tests), Production (multi-instance, monitored)

---

## 15. Design Trade-offs

| Decision | Alternatives Considered | Chosen | Why |
|---|---|---|---|
| Coordination model | Fully centralized / fully decentralized | Hybrid (thin coordinator + decentralized store access) | Avoids bottleneck of full centralization and conflict chaos of full decentralization |
| Datastore | Dedicated graph DB / dedicated vector DB / Postgres+pgvector | Postgres+pgvector | Single consistency boundary for v1; revisit graph DB if traversal patterns demand it |
| "Never lost" implementation | Delete + rely on backups / append-only log + supersede edges | Append-only log + supersede edges | Makes durability an architectural guarantee, not an operational promise |
| Internal API style | REST everywhere / GraphQL / gRPC internal + REST external | gRPC internal + REST/MCP external | Performance where it matters (internal), simplicity where it matters (external/agent-facing) |
| Initial architecture style | Microservices / Serverless / Modular monolith | Modular monolith with event-driven core | Matches current team size and load; structured for a clean future split |

---

## 16. Architecture Diagram

```
                              +-------------------+
                              |      Users          |
                              +---------+-----------+
                                        |
                              +---------v-----------+
                              |  Browser Chat UI     |
                              +---------+-----------+
                                        | REST / WebSocket
                              +---------v-----------+
                              |    API Gateway        |<----- Auth Service
                              +----+-------+----+-----+
                                   |       |    |
              +--------------------+       |    +--------------------+
              |                            |                          |
    +---------v---------+       +---------v---------+      +---------v---------+
    |   Local Agent       |       |   Cloud Agent       |      |  Browser Agent      |
    +---------+---------+       +---------+---------+      +---------+---------+
              |  MCP: read_context / write_context               |
              +----------------------------+-----------------------+
                                           |
                                 +---------v----------+
                                 | Coordination Service |
                                 |  (branch/merge,      |
                                 |   task assignment)    |
                                 +---------+-----------+
                                           |
                                 +---------v-----------+
                                 |   Context Service      |
                                 +----+-------+----+-----+
                                      |       |    |
                        +-------------+       |    +-------------+
                        |                     |                  |
              +---------v--------+  +--------v---------+ +------v-------+
              | Retrieval Service  |  |  Postgres+pgvector |  |    Redis      |
              | (embed/hybrid      |  |  (context graph,   |  | (locks, live  |
              |  search, summarize)|  |   event log)        |  |  presence)    |
              +---------+--------+  +--------------------+ +--------------+
                        |
              +---------v--------+
              |  Object Storage    |
              |  (artifacts)         |
              +--------------------+

                    (Monitoring/Observability stack observes all services)
                    (Anthropic API called by each Agent, not shown for clarity)
```

---

## 17. Implementation Roadmap

### Phase 1: MVP
- **Deliverables:** Context Service + Postgres/pgvector schema, basic MCP `read_context`/`write_context`, one local agent + one cloud agent working end-to-end on a toy project, simple browser chat view (read-only live feed)
- **Risks:** underestimating merge-conflict complexity; schema churn once real usage patterns emerge
- **Dependencies:** Anthropic API access, Postgres+pgvector hosting decision

### Phase 2: Scale
- **Deliverables:** Coordination Service split out with real branch/merge logic, hierarchical summarization pipeline, hybrid search, Redis-based locking and live presence, browser UI becomes interactive (not just read-only)
- **Risks:** conflict resolution UX (surfacing merges to users without overwhelming them); embedding pipeline becoming a bottleneck
- **Dependencies:** Phase 1 stable in production with real usage data to inform merge/retrieval tuning

### Phase 3: Enterprise Readiness
- **Deliverables:** multi-region option, full observability/alerting stack, compliance-ready data handling (if needed), horizontal scaling of Retrieval/Coordination services, formal SLAs
- **Risks:** multi-region consistency for the context graph is a genuinely hard problem, deferred deliberately to this phase
- **Dependencies:** demonstrated demand at a scale that justifies the added operational complexity

---

## 18. Final Architecture Review

**Acting as Principal Architect reviewing the above design:**

**Weaknesses identified:**
1. The hybrid coordination model (§13) still has the Coordination Service as a single logical point for conflict arbitration — under high concurrency, this could become a latency bottleneck even if it's not a full controller.
2. Postgres+pgvector as a single datastore for both graph structure and vector search is pragmatic but will strain once the context graph grows deep (multi-hop traversal queries get expensive in a relational model compared to a native graph DB).
3. Prompt injection risk (§10) is acknowledged but the mitigation (provenance tagging) is necessary, not sufficient — a malicious or compromised agent could still write convincing-looking instructions into shared context.
4. The MVP phase doesn't include any load testing of the merge/conflict path, which is the riskiest part of the whole system — it's easy to build a version that works with one agent and quietly fails under three.

**Bottlenecks:**
- Coordination Service under concurrent writes to overlapping context (mitigated by fine-grained per-unit locking, but worth explicit load testing before Phase 2)
- Embedding generation at write time (already mitigated via async queue, but queue depth needs its own alerting from day one, not added later)

**Security concerns:**
- Cross-agent trust: an agent reading context written by another agent implicitly trusts it. Recommend adding a lightweight "trust tier" per Context Unit (e.g., user-authored vs. agent-authored vs. external-tool-authored) so consuming agents/prompts can be built to treat these differently, rather than flattening all context into equally-trusted input.

**Scalability concerns:**
- Single-region, single-primary-Postgres design caps availability below 99.9%; acceptable for v1's stated 99.5% target but should be flagged now so it's not a surprise later.

**Improved final recommendation:**
- Keep the architecture as designed for Phase 1–2, but pull two items forward from "later" into explicit Phase 1 scope: (a) basic load testing of concurrent writes/merges with at least 3 simulated agents before calling MVP done, and (b) the trust-tier field on Context Units, since retrofitting it after content already exists without it is far more painful than including it in the initial schema. Everything else in the roadmap holds.
