\set ON_ERROR_STOP on

BEGIN;

CREATE TEMP TABLE expected_tables(schema_name text, table_name text, PRIMARY KEY(schema_name,table_name)) ON COMMIT DROP;
INSERT INTO expected_tables VALUES
('core','organizations'),('core','plants'),('core','user_profiles'),('core','user_roles'),('core','customers'),
('core','project_priorities'),('core','projects'),('core','project_lots'),('core','milestone_definitions'),('core','project_milestones'),
('capacity','work_centers'),('capacity','employees'),('capacity','skills'),('capacity','employee_skills'),
('capacity','physical_resource_types'),('capacity','physical_resources'),('capacity','physical_resource_groups'),
('capacity','physical_resource_group_members'),('capacity','calendars'),('capacity','calendar_working_intervals'),
('capacity','calendar_exceptions'),('capacity','resource_unavailabilities'),('capacity','overtime_authorizations'),
('production','operation_definitions'),('production','route_templates'),('production','route_versions'),('production','route_steps'),
('production','route_step_phase_templates'),('production','route_step_precedences'),('production','lot_route_assignments'),
('production','required_operations'),('production','required_operation_phases'),('production','operation_precedences'),
('production','operation_gates'),('production','operation_labor_requirements'),('production','operation_physical_requirements'),
('production','product_definition_revisions'),('production','production_batches'),('production','production_batch_versions'),
('production','production_batch_members'),('production','suppliers'),('production','material_requirements'),
('production','supplier_orders'),('production','supplier_order_lines'),('production','supplier_deliveries'),
('production','supplier_delivery_lines'),('production','material_allocations'),('production','drawing_packages'),
('production','drawing_releases'),('production','installation_lot_coverages'),('production','customer_availability_windows'),
('production','route_phase_labor_requirement_templates'),('production','route_phase_physical_requirement_templates'),
('production','route_phase_gate_templates'),
('planning','planning_state_heads'),('planning','planning_state_revisions'),('planning','effective_events'),
('planning','manual_exceptions'),('planning','planning_locks'),('planning','plan_versions'),('planning','scenarios'),
('planning','simulation_hypotheses'),('planning','impact_items'),('planning','schedule_solutions'),
('planning','operation_plan_results'),('planning','phase_plan_results'),('planning','planned_phase_assignments'),
('planning','assignment_segments'),('planning','human_segment_assignments'),('planning','physical_resource_reservations'),
('planning','physical_occupations'),('planning','solution_milestones'),
('execution','operation_executions'),('execution','execution_segments'),('execution','actual_resource_usages'),
('execution','remaining_estimate_revisions'),('execution','remaining_resource_estimates'),
('portal','public_stage_definitions'),('portal','public_stage_mapping_sets'),('portal','public_stage_mapping_rules'),
('portal','public_tracking_links'),('portal','public_project_projections'),('portal','public_timeline_entries'),
('portal','communicated_dates'),
('integration','inbox_messages'),('integration','outbox_messages'),('audit','audit_entries');

DO $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n FROM pg_namespace WHERE nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 8 THEN RAISE EXCEPTION 'Expected 8 application schemas, got %', n; END IF;

  SELECT count(*) INTO n FROM information_schema.tables t
   WHERE t.table_type='BASE TABLE' AND t.table_schema IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 87 THEN RAISE EXCEPTION 'Expected 87 application tables, got %', n; END IF;

  SELECT count(*) INTO n FROM expected_tables e
   WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables t WHERE t.table_schema=e.schema_name AND t.table_name=e.table_name AND t.table_type='BASE TABLE');
  IF n <> 0 THEN RAISE EXCEPTION '% expected tables are missing', n; END IF;

  SELECT count(*) INTO n FROM information_schema.tables t
   WHERE t.table_type='BASE TABLE' AND t.table_schema IN ('core','capacity','production','planning','execution','portal','integration','audit')
     AND NOT EXISTS (SELECT 1 FROM expected_tables e WHERE e.schema_name=t.table_schema AND e.table_name=t.table_name);
  IF n <> 0 THEN RAISE EXCEPTION '% unexpected application tables exist', n; END IF;

  SELECT count(*) INTO n FROM expected_tables e
   WHERE NOT EXISTS (
     SELECT 1 FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
      WHERE c.contype='p' AND s.nspname=e.schema_name AND r.relname=e.table_name
   );
  IF n <> 0 THEN RAISE EXCEPTION '% tables have no primary key', n; END IF;

  SELECT count(*) INTO n FROM expected_tables e
   WHERE NOT (e.schema_name='core' AND e.table_name='organizations')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns c WHERE c.table_schema=e.schema_name AND c.table_name=e.table_name AND c.column_name='organization_id' AND c.is_nullable='NO');
  IF n <> 0 THEN RAISE EXCEPTION '% tenant-owned tables lack NOT NULL organization_id', n; END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pgcrypto') THEN RAISE EXCEPTION 'pgcrypto missing'; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='btree_gist') THEN RAISE EXCEPTION 'btree_gist missing'; END IF;
END $$;

DO $$
DECLARE n integer;
BEGIN
  WITH fks AS (
    SELECT c.*, child.oid child_oid, parent.oid parent_oid,
           child_ns.nspname child_schema, child.relname child_table,
           parent_ns.nspname parent_schema, parent.relname parent_table,
           (SELECT attnum FROM pg_attribute WHERE attrelid=child.oid AND attname='organization_id') child_org_att,
           (SELECT attnum FROM pg_attribute WHERE attrelid=parent.oid AND attname='organization_id') parent_org_att
      FROM pg_constraint c
      JOIN pg_class child ON child.oid=c.conrelid
      JOIN pg_namespace child_ns ON child_ns.oid=child.relnamespace
      JOIN pg_class parent ON parent.oid=c.confrelid
      JOIN pg_namespace parent_ns ON parent_ns.oid=parent.relnamespace
     WHERE c.contype='f'
       AND child_ns.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
       AND parent_ns.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
       AND NOT (parent_ns.nspname='core' AND parent.relname='organizations')
  )
  SELECT count(*) INTO n FROM fks
   WHERE child_org_att IS NULL OR parent_org_att IS NULL
      OR NOT (child_org_att = ANY(conkey)) OR NOT (parent_org_att = ANY(confkey));
  IF n <> 0 THEN RAISE EXCEPTION '% tenant-owned foreign keys do not include organization_id', n; END IF;

  SELECT count(*) INTO n
    FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE c.contype='f' AND c.confdeltype='c'
     AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 0 THEN RAISE EXCEPTION '% destructive ON DELETE CASCADE constraints found', n; END IF;
END $$;

DO $$
DECLARE n integer;
BEGIN
  SELECT count(*) INTO n
    FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE c.contype='p' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 87 THEN RAISE EXCEPTION 'Expected 87 primary keys, got %', n; END IF;

  SELECT count(*) INTO n
    FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE c.contype='f' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 297 THEN RAISE EXCEPTION 'Expected 297 foreign keys, got %', n; END IF;

  SELECT count(*) INTO n
    FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE c.contype='u' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 159 THEN RAISE EXCEPTION 'Expected 159 unique constraints, got %', n; END IF;

  SELECT count(*) INTO n
    FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE c.contype='c' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 157 THEN RAISE EXCEPTION 'Expected 157 check constraints (M14), got %', n; END IF;

  SELECT count(*) INTO n
    FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE c.contype='x' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 7 THEN RAISE EXCEPTION 'Expected 7 exclusion constraints, got %', n; END IF;

  SELECT count(*) INTO n FROM pg_indexes
   WHERE schemaname IN ('core','capacity','production','planning','execution','portal','integration','audit');
  IF n <> 290 THEN RAISE EXCEPTION 'Expected 290 indexes, got %', n; END IF;

  SELECT count(*) INTO n
    FROM pg_proc p JOIN pg_namespace s ON s.oid=p.pronamespace
   WHERE (s.nspname,p.proname) IN (
     ('production','enforce_required_operation_lot_project'),
     ('production','enforce_installation_operation'),
     ('execution','enforce_actual_usage_work_segment'),
     ('planning','enforce_solution_scenario_bases')
   );
  IF n <> 4 THEN RAISE EXCEPTION 'Expected 4 minimum integrity functions, got %', n; END IF;

  SELECT count(*) INTO n
    FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid JOIN pg_namespace s ON s.oid=r.relnamespace
   WHERE NOT t.tgisinternal AND t.tgenabled <> 'D'
     AND (s.nspname,r.relname,t.tgname) IN (
       ('production','required_operations','trg_required_operation_lot_project'),
       ('production','installation_lot_coverages','trg_installation_coverages_operation_kind'),
       ('production','customer_availability_windows','trg_customer_windows_operation_kind'),
       ('execution','actual_resource_usages','trg_actual_usage_work_segment'),
       ('planning','schedule_solutions','trg_solution_scenario_bases')
     );
  IF n <> 5 THEN RAISE EXCEPTION 'Expected 5 enabled minimum integrity triggers, got %', n; END IF;
END $$;

SELECT 'schemas' AS check_name, count(*)::text AS result FROM pg_namespace WHERE nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'tables', count(*)::text FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'primary_keys', count(*)::text FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE c.contype='p' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'foreign_keys', count(*)::text FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE c.contype='f' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'unique_constraints', count(*)::text FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE c.contype='u' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'check_constraints', count(*)::text FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE c.contype='c' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'not_null_constraints', count(*)::text FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE c.contype='n' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'exclusions', count(*)::text FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE c.contype='x' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'indexes', count(*)::text FROM pg_indexes WHERE schemaname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'minimum_functions', count(*)::text FROM pg_proc p JOIN pg_namespace s ON s.oid=p.pronamespace WHERE s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'enabled_user_triggers', count(*)::text FROM pg_trigger t JOIN pg_class r ON r.oid=t.tgrelid JOIN pg_namespace s ON s.oid=r.relnamespace WHERE NOT t.tgisinternal AND t.tgenabled <> 'D' AND s.nspname IN ('core','capacity','production','planning','execution','portal','integration','audit')
UNION ALL
SELECT 'required_extensions', count(*)::text FROM pg_extension WHERE extname IN ('pgcrypto','btree_gist')
ORDER BY check_name;

ROLLBACK;
