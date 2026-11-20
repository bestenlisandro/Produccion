-- Apply on the restored cloud database as the owner, after creating
-- produccion_besten_app as a non-owner LOGIN with a separate password.
BEGIN;

GRANT USAGE ON SCHEMA core, capacity, production, planning, execution, audit, portal, integration
    TO produccion_besten_app;
GRANT SELECT ON ALL TABLES IN SCHEMA core, capacity, production, planning, execution, audit, portal, integration
    TO produccion_besten_app;
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA core, capacity, production, planning, execution
    TO produccion_besten_app;
REVOKE INSERT, UPDATE ON core.organizations, core.user_profiles, core.user_roles
    FROM produccion_besten_app;
-- SELECT FOR UPDATE on the organization requires an UPDATE column privilege.
GRANT UPDATE (updated_at) ON core.organizations TO produccion_besten_app;
GRANT DELETE ON capacity.calendar_working_intervals, production.operation_labor_requirements
    TO produccion_besten_app;
GRANT INSERT ON audit.audit_entries, integration.outbox_messages TO produccion_besten_app;
GRANT UPDATE (after_data) ON audit.audit_entries TO produccion_besten_app;

COMMIT;
