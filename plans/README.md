# Loom — Implementation Plans

This directory contains the complete, phased implementation plan for the **Loom** project: a multi-agent shared-context system where AI agents collaborate on projects via an append-only, never-lost event log.

## How to Use These Plans

Each file is a self-contained subtask specification that you can hand directly to the **Core Orchestration Agent**. The agent will run its full pipeline (Architect → Planner → Tester → Coder → Verify → Review → Security → Docs) on each subtask.

### Execution Rules
- **Within a phase**, follow the numbered order strictly (each subtask depends on prior ones)
- **Between phases**, complete Phase 0 first, then Phase 1, then Phase 2, then Phase 3
- Each subtask file lists its dependencies at the top of the file
- Each subtask file includes TDD instructions (write these tests first)

---

## Phase 0 — Foundation

Sets up the development environment, CI pipeline, and the orchestrator tool.

| # | Subtask | File | Description |
|---|---------|------|-------------|
| 0.1 | **Project Scaffold** | `phase-0/01-project-scaffold.md` | Repo skeleton: directory structure, README, LICENSE, .gitignore, pyproject.toml |
| 0.2 | **Dev Environment** | `phase-0/02-dev-environment.md` | Docker Compose (Postgres+pgvector, Redis), .env.example, health check scripts |
| 0.3 | **CI/CD Pipeline** | `phase-0/03-ci-cd.md` | GitHub Actions: lint, test, security scan, deploy stub |
| 0.4 | **Orchestrator CLI** | `phase-0/04-orchestrator-cli.md` | Python CLI for the checkpoint-graph build pipeline |

---

## Phase 1 — MVP

The read-write context path, MCP tools, basic coordination, async embedding, one working agent, and a browser feed.

| # | Subtask | File | Key Deliverable |
|---|---------|------|-----------------|
| 1.1 | **Database Schema** | `phase-1/01-db-schema.md` | Postgres+pgvector schema with trust-tier, client_uuid, version fields |
| 1.2 | **Context Write Path** | `phase-1/02-context-service-write.md` | POST endpoint, transactional write, event log append |
| 1.3 | **Context Read Path** | `phase-1/03-context-service-read.md` | GET endpoint, keyword search, token-budget packing |
| 1.4 | **Event Log** | `phase-1/04-event-log.md` | Append-only immutable ledger, projection rebuild script |
| 1.5 | **MCP Tools** | `phase-1/05-mcp-tools.md` | read_context, write_context, get_project_summary MCP tools |
| 1.6 | **Idempotency & Versioning** | `phase-1/06-idempotency.md` | Client UUID dedup, optimistic concurrency |
| 1.7 | **Trust-Tier Field** | `phase-1/07-trust-tier.md` | Trust tier ENUM, auth enforcement, retrieval weighting |
| 1.8 | **Basic Coordination** | `phase-1/08-basic-coordination.md` | Conflict detection, auto-merge, pending branches |
| 1.9 | **Embedding Pipeline** | `phase-1/09-embedding-pipeline.md` | Async queue + worker, pgvector update, DLQ |
| 1.10 | **Local Agent** | `phase-1/10-local-agent.md` | End-to-end agent: read → LLM → write |
| 1.11 | **Browser UI (Read-Only)** | `phase-1/11-browser-ui-feed.md` | WebSocket live feed with trust-tier badges |
| 1.12 | **Load Test: Merges** | `phase-1/12-load-test-merges.md` | 3+ concurrent agents, conflict/latency metrics |

---

## Phase 2 — Scale

Full coordination, rich retrieval, interactive UI, and multi-agent demos.

| # | Subtask | File | Key Deliverable |
|---|---------|------|-----------------|
| 2.1 | **Full Coordination** | `phase-2/01-full-coordination.md` | Redis locks, git-style branch/merge, task assignment |
| 2.2 | **Hierarchical Summarization** | `phase-2/02-summarization.md` | Summary context units, LLM-based condensation |
| 2.3 | **Hybrid Search** | `phase-2/03-hybrid-search.md` | Vector + keyword RRF, token-budget packing |
| 2.4 | **Live Presence** | `phase-2/04-live-presence.md` | Redis heartbeats, agent status, lock monitoring |
| 2.5 | **Interactive Browser UI** | `phase-2/05-interactive-ui.md` | Context graph browser, conflict resolution, task mgmt |
| 2.6 | **Multi-Agent Demo** | `phase-2/06-multi-agent-demo.md` | 3 agents (local/cloud/browser) concurrent demo |

---

## Phase 3 — Enterprise

Production hardening, observability, compliance, and global scale.

| # | Subtask | File | Key Deliverable |
|---|---------|------|-----------------|
| 3.1 | **Observability Stack** | `phase-3/01-observability.md` | Structured logging, OpenTelemetry tracing, Prometheus metrics, Grafana |
| 3.2 | **Auth & Authorization** | `phase-3/02-auth-authz.md` | Agent API keys, JWT sessions, RBAC, secrets management |
| 3.3 | **Multi-Region** | `phase-3/03-multi-region.md` | Cross-region Postgres replicas, global Gateway, cross-region Redis |
| 3.4 | **Compliance** | `phase-3/04-compliance.md` | Retention policies, audit export, PII scanning, GDPR erasure |
| 3.5 | **Autoscaling** | `phase-3/05-autoscaling.md` | Kubernetes HPA, queue-based scaling, load test suite |

---

## Quick Start

```bash
# 1. Hand the Core Agent this prompt:
"Execute phase-0/01-project-scaffold.md"

# 2. After it completes, hand it the next:
"Execute phase-0/02-dev-environment.md"

# 3. Continue through the numbered order...
```

Each subtask is designed for a single agent execution. The TDD instructions at the bottom of each file tell the agent which tests to write before implementing. Every subtask produces a checkpoint in the orchestrator state graph.
