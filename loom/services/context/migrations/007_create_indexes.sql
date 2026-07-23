CREATE INDEX IF NOT EXISTS idx_context_units_project
    ON context_units(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_context_units_client_uuid
    ON context_units(client_uuid);

CREATE INDEX IF NOT EXISTS idx_context_units_embedding
    ON context_units USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_context_units_content_gin
    ON context_units USING gin(to_tsvector('english', content));

CREATE INDEX IF NOT EXISTS idx_context_edges_child
    ON context_edges(child_id);

CREATE INDEX IF NOT EXISTS idx_context_edges_parent
    ON context_edges(parent_id);

CREATE INDEX IF NOT EXISTS idx_event_log_project
    ON event_log(project_id, created_at ASC);
