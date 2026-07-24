from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from loom.api.routers import agents, conflicts, context, projects

app = FastAPI(
    title="Loom API",
    description=(
        "Loom context server — bridges browser AI chats and"
        " CLI agents into a shared context store"
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context.router, prefix="/v1/projects", tags=["context"])
app.include_router(agents.router, prefix="/v1", tags=["agents"])
app.include_router(conflicts.router, prefix="/v1/projects", tags=["conflicts"])
app.include_router(projects.router, prefix="/v1/projects", tags=["projects"])


@app.get("/health")
async def health():
    return {"status": "ok"}
