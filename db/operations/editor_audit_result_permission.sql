-- Operational permission repair; not a schema migration.
-- Run as the database owner in produccion_besten.
-- The editor completes its own replay result inside the same transaction.
-- No general UPDATE, DELETE, ownership or administrative privilege is granted.
BEGIN;
GRANT UPDATE (after_data) ON TABLE audit.audit_entries TO produccion_besten_app;
COMMIT;
