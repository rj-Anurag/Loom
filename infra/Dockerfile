FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY loom ./loom
COPY agents ./agents
RUN pip install .

RUN addgroup --system loom && adduser --system --ingroup loom loom
USER loom

EXPOSE 8000

CMD ["python", "-m", "loom.api.start"]
