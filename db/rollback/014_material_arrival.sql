BEGIN;
ALTER TABLE core.project_lots DROP CONSTRAINT ck_project_lots_material_arrival,
    DROP COLUMN material_arrival;
COMMIT;
