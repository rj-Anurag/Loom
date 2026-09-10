FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY loom ./loom
COPY agents ./agents
RUN uv sync --frozen --no-dev --no-editable

RUN addgroup --system loom && adduser --system --ingroup loom loom
USER loom

EXPOSE 8000

CMD ["python", "-m", "loom.api.start"]
