BEGIN;
-- Refuse to discard newly authored human demand on downgrade.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM production.required_operation_phases WHERE required_people <> 0) THEN
        RAISE EXCEPTION 'Independent human demand must be preserved before downgrading M13';
    END IF;
END $$;
ALTER TABLE production.required_operation_phases DROP COLUMN required_people;
COMMIT;
