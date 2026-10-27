BEGIN;
-- Catalog names/IDs are retained; only the presentation-order extension is removed.
ALTER TABLE production.operation_definitions DROP COLUMN display_order;
COMMIT;
