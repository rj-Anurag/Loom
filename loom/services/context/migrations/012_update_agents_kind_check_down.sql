DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM agents WHERE kind = 'system') THEN
        RAISE EXCEPTION 'Cannot roll back agent kind migration while system agents exist';
    END IF;
END $$;

ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_kind;
ALTER TABLE agents ADD CONSTRAINT agents_kind_check
    CHECK (kind IN ('local', 'cloud', 'browser'));
