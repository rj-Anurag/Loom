#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MIGRATIONS_DIR="${MIGRATIONS_DIR:-$PROJECT_ROOT/loom/services/context/migrations}"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/infra/docker-compose.yml}"

# Run psql via docker compose exec (no local psql needed on macOS).
psql_loom() {
    docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U loom -d loom "$@"
}

ensure_migrations_table() {
    psql_loom -c "
        CREATE TABLE IF NOT EXISTS _migrations (
            id SERIAL PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    " 2>/dev/null
}

apply_migration() {
    local file="$1"
    local filename
    filename=$(basename "$file")
    echo "  Applying: $filename"
    psql_loom -v ON_ERROR_STOP=1 < "$file"
    psql_loom -c "
        INSERT INTO _migrations (filename) VALUES ('$filename');
    " 2>/dev/null
}

rollback_migration() {
    local filename
    filename=$(psql_loom -At -c \
        "SELECT filename FROM _migrations ORDER BY id DESC LIMIT 1;" 2>/dev/null)
    if [ -z "$filename" ]; then
        echo "No applied migrations to roll back."
        return 0
    fi

    local down_file="$MIGRATIONS_DIR/${filename%.sql}_down.sql"
    if [ ! -f "$down_file" ]; then
        echo "No rollback migration found for $filename: $down_file" >&2
        return 1
    fi

    echo "  Rolling back: $filename"
    psql_loom -v ON_ERROR_STOP=1 < "$down_file"
    psql_loom -v ON_ERROR_STOP=1 -c \
        "DELETE FROM _migrations WHERE filename = '$filename';"
}

case "${1:-up}" in
    up)
        ensure_migrations_table
        echo "Applying pending migrations..."
        if [ -d "$MIGRATIONS_DIR" ]; then
            for file in "$MIGRATIONS_DIR"/[0-9][0-9][0-9]_*.sql; do
                [ "${file%_down.sql}" = "$file" ] || continue
                [ -f "$file" ] || continue
                filename=$(basename "$file")
                applied=$(psql_loom -t -c "
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
