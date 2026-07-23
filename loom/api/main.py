from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from loom.api.routers import agents, context

app = FastAPI(
    title="Loom API",
    description="Multi-agent shared-context collaboration platform",
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


@app.get("/health")
async def health():
    return {"status": "ok"}
