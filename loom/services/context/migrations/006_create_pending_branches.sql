CREATE TABLE IF NOT EXISTS pending_branches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_unit_id UUID NOT NULL REFERENCES context_units(id),
    conflict_type   TEXT NOT NULL,
    resolution      TEXT DEFAULT 'pending' CHECK (resolution IN ('pending', 'auto_merged', 'resolved')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
