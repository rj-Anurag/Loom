---
title: "Phase 1.9 — Async Embedding Pipeline"
description: "Redis-backed queue for async embedding generation. Worker process that computes embeddings and updates pgvector. Dead-letter queue for failed jobs."
status: pending
dependencies: ["phase-1/02-context-service-write.md"]
---

# Async Embedding Pipeline

## Description
When a context unit is written, its embedding vector must be computed and stored for vector similarity search. This is done asynchronously via a queue to avoid blocking the write path. The pipeline consists of: (1) a queue producer in the write path, (2) a worker that consumes jobs, (3) a dead-letter queue for failures.

## Architecture

```
Write Path → enqueue job (Redis LIST) → Worker picks up → compute embedding → UPDATE pgvector
                                              ↓ (on failure)
                                         Dead Letter Queue (Redis LIST)
                                              ↓ (manual retry)
                                         Retry → Worker
```

## Queue Producer

In `services/context/service.py`, after the write transaction commits:

```python
import redis.asyncio as redis

async def enqueue_embedding_job(context_unit_id: str, content: str):
    r = redis.from_url(settings.REDIS_URL)
    await r.lpush("embedding:queue", json.dumps({
        "context_unit_id": context_unit_id,
        "content": content[:5000],  # Limit content size for queue
        "attempt": 1
    }))
```

## Embedding Worker

Create `services/retrieval/embedding_worker.py`:

```python
async def process_embedding_job(job: dict):
    context_unit_id = job["context_unit_id"]
    content = job["content"]
    try:
        # For v1, use a simple embedding model
        # Option A: sentence-transformers (local)
        # Option B: OpenAI embeddings API
        # Option C: random vector stub (for testing)
        embedding = await compute_embedding(content)
        await db.execute(
            "UPDATE context_units SET embedding = $1 WHERE id = $2",
            embedding, context_unit_id
        )
    except Exception as e:
        # Send to DLQ
        await r.lpush("embedding:dlq", json.dumps({
            **job,
            "error": str(e),
            "failed_at": datetime.utcnow().isoformat()
        }))
```

### Worker Loop

```python
async def worker_loop():
    r = redis.from_url(settings.REDIS_URL)
    while True:
        job_data = await r.brpoplpush(
            "embedding:queue", "embedding:inprogress", timeout=30
        )
        if job_data:
            job = json.loads(job_data)
            await process_embedding_job(job)
            await r.lrem("embedding:inprogress", 0, job_data)
```

## Dead Letter Queue

- Failed jobs land in `embedding:dlq`
- A retry script (or manual trigger) can replay DLQ items back to the main queue
- DLQ items include: `context_unit_id`, `content`, `error`, `failed_at`, `attempt`
- Max 3 attempts before permanent failure (logged for investigation)

## Embedding Model (v1)

For v1, use a configurable embedding function:

```python
async def compute_embedding(text: str) -> list[float]:
    """
    Configurable embedding function.
    Default: random vector of dimension 1536 (for testing).
    When configured: uses OpenAI text-embedding-ada-002 or sentence-transformers.
    """
    if settings.EMBEDDING_PROVIDER == "openai":
        resp = await openai.Embedding.acreate(
            model="text-embedding-ada-002",
            input=text
        )
        return resp["data"][0]["embedding"]
    elif settings.EMBEDDING_PROVIDER == "sentence_transformers":
        import sentence_transformers
        model = sentence_transformers.SentenceTransformer(
            "all-MiniLM-L6-v2"
        )
        return model.encode(text).tolist()
    else:
        # Deterministic random stub for testing
        import hashlib
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return [rng.gauss(0, 1) for _ in range(1536)]
```

## File Targets
- `services/context/service.py` — add `enqueue_embedding_job()` call
- `services/retrieval/__init__.py` — package init
- `services/retrieval/embedding_worker.py` — worker loop, compute_embedding
- `scripts/run-embedding-worker.sh` — entrypoint script for the worker process

## Acceptance Criteria

- [ ] Write path enqueues an embedding job after commit
- [ ] Worker picks up the job and computes an embedding
- [ ] `context_units.embedding` is populated after worker runs
- [ ] Failed jobs land in the dead-letter queue
- [ ] DLQ items can be retried (re-pushed to main queue)
- [ ] Worker handles graceful shutdown (SIGTERM)
- [ ] Multiple workers can run concurrently (each picks up different jobs)

## TDD Instructions

```python
@pytest.mark.asyncio
async def test_write_enqueues_embedding_job(client, test_project, redis_client):
    body = {"client_uuid": str(uuid4()), "type": "message", "content": "test embedding", "version": 1}
    await client.post(f"/v1/projects/{test_project}/context", json=body)
    queue_len = await redis_client.llen("embedding:queue")
    assert queue_len == 1

@pytest.mark.asyncio
async def test_worker_processes_job_and_updates_db(redis_client, db):
    job = {"context_unit_id": str(uuid4()), "content": "test"}
    await redis_client.lpush("embedding:queue", json.dumps(job))
    # Run worker once
    await process_embedding_job(job)
    # Verify embedding is set in DB
    row = await db.fetchrow("SELECT embedding FROM context_units WHERE id = $1", job["context_unit_id"])
    assert row["embedding"] is not None
```

## Dependencies
- Phase 1.2 (write path)
- Phase 0.2 (Redis must be running)
