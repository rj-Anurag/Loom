ALTER TABLE context_units
    ADD COLUMN IF NOT EXISTS source_type TEXT,
    ADD COLUMN IF NOT EXISTS source_session_id TEXT,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE context_units AS context
SET source_type = CASE
    WHEN agent.kind = 'browser' THEN 'browser_chat'
    ELSE 'mcp_agent'
END
FROM agents AS agent
WHERE context.agent_id = agent.id
  AND context.source_type IS NULL;

UPDATE context_units
SET source_type = 'mcp_agent'
WHERE source_type IS NULL;

ALTER TABLE context_units
    ALTER COLUMN source_type SET DEFAULT 'mcp_agent',
    ALTER COLUMN source_type SET NOT NULL;

DO $$ BEGIN
    ALTER TABLE context_units
        ADD CONSTRAINT ck_context_units_source_type
        CHECK (source_type IN (
            'browser_chat',
            'codex_cli',
            'claude_code',
            'opencode',
            'manual_cli',
            'dashboard',
            'mcp_agent'
        ));
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;
