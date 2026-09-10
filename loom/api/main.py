import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as redis_async
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from loom.api.dependencies import get_redis
from loom.api.routers import (
    agents,
    auth,
    branches,
    conflicts,
    context,
    events,
    extension,
    projects,
    tasks,
)
from loom.db import get_session

logger = logging.getLogger(__name__)
WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan handler for startup/shutdown events.

    Starts a background task that periodically sweeps for offline agents
    and emits ``agent_offline`` events.
    """
    try:
        sweep_task = asyncio.create_task(_periodic_offline_sweep())
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        from loom.services.retrieval.queue import close_redis

        await close_redis()


async def _periodic_offline_sweep() -> None:
    """Every 30s, emit ``agent_offline`` for agents whose keys expired.

    Compares the current active set against the previously known set.
    Emits ``agent_offline`` for agents that disappeared from Redis.
    """
    from loom.schemas.events import ProjectEvent
    from loom.services.coordination.presence import PRESENCE_KEY_PREFIX
    from loom.services.events.manager import connection_manager

    previous: dict[str, set[str]] = {}  # project_id → {agent_id}

    while True:
        try:
            from loom.services.retrieval.queue import get_redis as _get_queue_redis

            redis = _get_queue_redis()
            if redis is None:
                await asyncio.sleep(30)
                continue

            cursor = 0
            active_by_project: dict[str, set[str]] = {}

            while True:
                cursor, keys = await redis.scan(
                    cursor=cursor, match=f"{PRESENCE_KEY_PREFIX}*", count=100
                )
                if keys:
                    pipe = redis.pipeline()
                    for key in keys:
                        pipe.hgetall(key)
                    results = await pipe.execute()
                    for key, data in zip(keys, results):
                        if data:
                            key_text = key.decode() if isinstance(key, bytes) else key
                            agent_id = key_text[len(PRESENCE_KEY_PREFIX):]
                            raw_pid = data.get("project_id", "")
                            pid = raw_pid.decode() if isinstance(raw_pid, bytes) else raw_pid
                            if pid:
                                active_by_project.setdefault(pid, set()).add(agent_id)
                if cursor == 0:
                    break

            # Compare with previous set → emit agent_offline for each gone agent
            for pid, prev_agents in previous.items():
                current_agents = active_by_project.get(pid, set())
                for agent_id in prev_agents - current_agents:
                    event = ProjectEvent(
                        type="agent_offline",
                        project_id=pid,
                        payload={"agent_id": agent_id},
                        timestamp=datetime.now(UTC).isoformat(),
                    ).model_dump()
                    await connection_manager.broadcast(pid, event)

            previous = active_by_project
        except Exception:
            logger.exception("Error in periodic offline sweep")

        await asyncio.sleep(30)


app = FastAPI(
    title="Loom API",
    description=(
        "Loom context server — bridges browser AI chats and"
        " CLI agents into a shared context store"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Bearer authentication does not require browser credentials/cookies.
    # Keep origins configurable at the reverse-proxy level without combining
    # wildcard origins with credentialed CORS.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context.router, prefix="/v1/projects", tags=["context"])
app.include_router(auth.router, tags=["auth"])
app.include_router(events.router, prefix="/v1/projects", tags=["events"])
app.include_router(agents.router, prefix="/v1", tags=["agents"])
app.include_router(conflicts.router, prefix="/v1/projects", tags=["conflicts"])
app.include_router(projects.router, prefix="/v1/projects", tags=["projects"])
app.include_router(extension.router, tags=["extension"])
app.include_router(branches.router, prefix="/v1/projects", tags=["branches"])
app.include_router(tasks.router, prefix="/v1/projects", tags=["tasks"])

app.mount("/static", StaticFiles(directory=str(WEB_ROOT)), name="static")


@app.get("/")
@app.get("/dashboard")
async def public_dashboard() -> FileResponse:
    return FileResponse(WEB_ROOT / "account.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def check_readiness(
    session: AsyncSession,
    redis: redis_async.Redis | None,
) -> dict[str, str]:
    """Check required dependencies without leaking connection details."""
    status = {"database": "unavailable", "redis": "unavailable"}
    try:
        await session.execute(text("SELECT 1"))
        status["database"] = "ok"
    except Exception:
        logger.warning("Readiness database check failed")

    if redis is not None:
        try:
            await redis.ping()
            status["redis"] = "ok"
        except Exception:
            logger.warning("Readiness Redis check failed")
    return status


@app.get("/ready")
async def readiness(
    session: AsyncSession = Depends(get_session),
    redis: redis_async.Redis | None = Depends(get_redis),
) -> dict[str, str]:
    status = await check_readiness(session, redis)
    if "unavailable" in status.values():
        raise HTTPException(status_code=503, detail=status)
    return status


@app.get("/v1/projects/{project_id}/dashboard")
async def project_dashboard(project_id: str) -> FileResponse:
    return FileResponse(WEB_ROOT / "dashboard.html")
