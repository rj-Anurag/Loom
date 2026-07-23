---
title: "Phase 3.1 — Full Observability Stack"
description: "Structured logging, distributed tracing, metrics collection, and alerting for all Loom services."
status: pending
dependencies: ["phase-1/02-context-service-write.md", "phase-1/03-context-service-read.md"]
---

# Full Observability Stack

## Description
Add structured logging, distributed tracing (OpenTelemetry), Prometheus metrics, and alerting rules to every Loom service. This enables debugging, performance monitoring, and incident response.

## Structured Logging

### Log Format
All services emit JSON-structured logs:
```json
{
    "timestamp": "2026-07-23T12:00:00.000Z",
    "level": "INFO|WARN|ERROR|DEBUG",
    "service": "context-service",
    "trace_id": "abc123",
    "span_id": "def456",
    "message": "Context unit written",
    "context_unit_id": "uuid",
    "project_id": "uuid",
    "agent_id": "uuid",
    "duration_ms": 45,
    "error": null
}
```

### Implementation
Use `structlog` (Python) for structured logging:
```python
import structlog

logger = structlog.get_logger()
logger.info("context_unit_written",
            context_unit_id=str(unit_id),
            project_id=str(project_id),
            agent_id=str(agent_id),
            duration_ms=duration)
```

## Distributed Tracing

### OpenTelemetry Setup
```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider

provider = TracerProvider()
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.OTEL_ENDPOINT))
)
trace.set_tracer_provider(provider)
```

### Traced Operations
Every agent turn is traced end-to-end:
```
read_context → LLM call → write_context
    ↓             ↓            ↓
  Span 1       Span 2       Span 3
    └──────────┴──────────────┘
         Trace (agent turn)
```

### Trace Context Propagation
Trace headers are propagated via HTTP headers:
- `traceparent` — W3C trace context
- `tracestate` — vendor-specific trace data

## Metrics

### Prometheus Metrics

**Context Service:**
- `loom_writes_total` — counter, labels: project, status (success/conflict/error)
- `loom_write_duration_ms` — histogram, labels: project
- `loom_reads_total` — counter, labels: project
- `loom_read_duration_ms` — histogram, labels: project

**Coordination Service:**
- `loom_conflicts_total` — counter, labels: project, type (version/overlap)
- `loom_merges_total` — counter, labels: project, strategy (auto/manual)
- `loom_locks_held` — gauge
- `loom_lock_contention_ms` — histogram

**Retrieval Service:**
- `loom_embeddings_queued` — gauge
- `loom_embeddings_processed_total` — counter
- `loom_embeddings_failed_total` — counter
- `loom_search_duration_ms` — histogram, labels: type (vector/keyword/hybrid)

**System:**
- `loom_active_agents` — gauge
- `loom_event_log_size` — gauge
- `loom_context_units_total` — gauge

### Metrics Endpoint
```
GET /metrics — Prometheus scrape endpoint
```

## Alerting Rules

| Alert | Condition | Severity |
|---|---|---|
| High write conflict rate | `loom_conflicts_total > 5% of writes` over 5m | Warning |
| Embedding queue backlog | `loom_embeddings_queued > 100` for 5m | Warning |
| Write latency spike | `loom_write_duration_ms_p99 > 1000` for 5m | Critical |
| High error rate | `loom_writes_total{status="error"} > 2%` for 5m | Critical |
| Agent offline | `loom_active_agents` drops by > 50% | Warning |
| Event log growth spike | `loom_event_log_size` grows > 10% in 1h | Info |

## File Targets
- `api/middleware.py` — add tracing middleware, structured logging
- `services/context/service.py` — add metrics instrumentation
- `services/coordination/service.py` — add metrics instrumentation
- `services/retrieval/embedding_worker.py` — add metrics instrumentation
- `infra/prometheus.yml` — Prometheus config
- `infra/grafana/dashboards/` — Grafana dashboard JSON

## Acceptance Criteria
- [ ] All services emit structured JSON logs
- [ ] Distributed tracing spans the full agent turn
- [ ] Prometheus metrics are exposed at /metrics
- [ ] Metrics are labelled by project, service, and status
- [ ] Grafana dashboards show key metrics
- [ ] Alerting rules are configured and tested

## TDD Instructions
```python
def test_structured_logging_output(caplog, context_service):
    context_service.write_context(...)
    record = caplog.records[-1]
    assert record.service == "context-service"
    assert "context_unit_id" in record.__dict__

@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "loom_writes_total" in resp.text
```

## Dependencies
- Phase 1.2 (write path to instrument)
- Phase 1.3 (read path to instrument)
