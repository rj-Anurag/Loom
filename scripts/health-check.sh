#!/usr/bin/env bash
set -euo pipefail

# Default to docker service names when running in compose
PG_HOST="${PGHOST:-localhost}"
PG_PORT="${PGPORT:-5432}"
REDIS_HOST="${REDISHOST:-localhost}"
REDIS_PORT="${REDISPORT:-6379}"

echo "Checking Postgres..."
if pg_isready -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom 2>/dev/null; then
    echo "  Postgres: OK"
else
    echo "  Postgres: FAILED"
    exit 1
fi

echo "Checking Redis..."
if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG; then
    echo "  Redis: OK"
else
    echo "  Redis: FAILED"
    exit 1
fi

echo "All services healthy."
