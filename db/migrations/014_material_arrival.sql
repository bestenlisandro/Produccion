BEGIN;
-- Initial-template intent belongs to the lot, independently of its editable DAG.
-- NULL preserves all existing definitions, snapshots and route assignments.
ALTER TABLE core.project_lots ADD COLUMN material_arrival jsonb,
    ADD CONSTRAINT ck_project_lots_material_arrival CHECK (
        material_arrival IS NULL OR jsonb_typeof(material_arrival) = 'object');
COMMIT;
