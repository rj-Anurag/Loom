#!/usr/bin/env bash
set -euo pipefail

MIGRATIONS_DIR="${MIGRATIONS_DIR:-loom/services/context/migrations}"
PG_HOST="${PGHOST:-localhost}"
PG_PORT="${PGPORT:-5432}"

ensure_migrations_table() {
    psql -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom -c "
        CREATE TABLE IF NOT EXISTS _migrations (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    " 2>/dev/null
}

apply_migration() {
    local file="$1"
    echo "  Applying: $file"
    psql -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom -f "$file" 2>/dev/null
    psql -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom -c "
        INSERT INTO _migrations (filename) VALUES ('$file');
    " 2>/dev/null
}

rollback_migration() {
    echo "Rollback not yet implemented for $1"
    exit 1
}

case "${1:-up}" in
    up)
        ensure_migrations_table
        echo "Applying pending migrations..."
        if [ -d "$MIGRATIONS_DIR" ]; then
            for file in "$MIGRATIONS_DIR"/*.sql; do
                filename=$(basename "$file")
                applied=$(psql -h "$PG_HOST" -p "$PG_PORT" -U loom -d loom -t -c "
                    SELECT COUNT(*) FROM _migrations WHERE filename = '$filename';
                " 2>/dev/null | tr -d ' ')
                if [ "$applied" = "0" ]; then
                    apply_migration "$file"
                fi
            done
        else
            echo "  No migrations directory found at $MIGRATIONS_DIR"
        fi
        echo "Migrations complete."
        ;;
    down)
        echo "Rolling back last migration..."
        rollback_migration "$@"
        ;;
    *)
        echo "Usage: $0 [up|down]"
        exit 1
        ;;
esac
