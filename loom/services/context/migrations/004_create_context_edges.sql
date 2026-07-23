DO $$ BEGIN
    CREATE TYPE edge_relation AS ENUM (
        'derived_from', 'supersedes', 'references', 'merged_from'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS context_edges (
    parent_id UUID NOT NULL REFERENCES context_units(id),
    child_id  UUID NOT NULL REFERENCES context_units(id),
    relation  edge_relation NOT NULL,
    PRIMARY KEY (parent_id, child_id, relation)
);
