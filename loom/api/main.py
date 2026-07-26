import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from loom.api.routers import agents, branches, conflicts, context, events, extension, projects, tasks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler for startup/shutdown events.

    Starts a background task that periodically sweeps for offline agents
    and emits ``agent_offline`` events.
    """
    sweep_task = asyncio.create_task(_periodic_offline_sweep())
    yield
    sweep_task.cancel()
    try:
        await sweep_task
    except asyncio.CancelledError:
        pass


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
                            agent_id = key[len(PRESENCE_KEY_PREFIX):]
                            pid = data.get("project_id", "")
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
                        timestamp=datetime.now(timezone.utc).isoformat(),
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context.router, prefix="/v1/projects", tags=["context"])
app.include_router(events.router, prefix="/v1/projects", tags=["events"])
app.include_router(agents.router, prefix="/v1", tags=["agents"])
app.include_router(conflicts.router, prefix="/v1/projects", tags=["conflicts"])
app.include_router(projects.router, prefix="/v1/projects", tags=["projects"])
app.include_router(extension.router, tags=["extension"])
app.include_router(branches.router, prefix="/v1/projects", tags=["branches"])
app.include_router(tasks.router, prefix="/v1/projects", tags=["tasks"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/projects/{project_id}/dashboard")
async def project_dashboard(project_id: str):
    return FileResponse("loom/web/dashboard.html")
