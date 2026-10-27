BEGIN;
-- Independent human demand. Zero preserves the pre-existing automatic-phase mode.
-- Skill requirements remain a collection with non-null, real skill references.
ALTER TABLE production.required_operation_phases
    ADD COLUMN required_people smallint NOT NULL DEFAULT 0,
    ADD CONSTRAINT ck_required_phases_people CHECK (required_people >= 0);
COMMIT;
