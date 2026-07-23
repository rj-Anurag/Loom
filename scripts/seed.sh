#!/usr/bin/env bash
set -euo pipefail

PG_HOST="${PGHOST:-localhost}"
PG_PORT="${PGPORT:-5432}"

echo "Seeding development database..."

# Enable pgvector extension
psql -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null

# Create a test project
psql -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom -c "
INSERT INTO projects (id, name)
SELECT gen_random_uuid(), 'Development Test Project'
WHERE NOT EXISTS (SELECT 1 FROM projects WHERE name = 'Development Test Project');
" 2>/dev/null

echo "Seed complete."
