BEGIN;

ALTER TABLE core.plants
  ADD CONSTRAINT fk_core_plants_base_calendar FOREIGN KEY (organization_id,base_calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_core_plants_communication_calendar FOREIGN KEY (organization_id,communication_calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_core_plants_current_definition FOREIGN KEY (organization_id,current_product_definition_revision_id) REFERENCES production.product_definition_revisions(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT fk_core_plants_current_plan FOREIGN KEY (organization_id,current_plan_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  ALTER COLUMN base_calendar_id SET NOT NULL;

ALTER TABLE production.product_definition_revisions
  ADD CONSTRAINT uq_production_definition_revisions_id_plant UNIQUE (organization_id,id,plant_id);
ALTER TABLE planning.planning_state_revisions
  ADD CONSTRAINT uq_planning_state_revisions_id_plant UNIQUE (organization_id,id,plant_id);
ALTER TABLE planning.plan_versions
  ADD CONSTRAINT uq_planning_plan_versions_id_plant UNIQUE (organization_id,id,plant_id);

ALTER TABLE core.plants
  ADD CONSTRAINT fk_core_plants_current_definition_same_plant FOREIGN KEY (organization_id,current_product_definition_revision_id,id) REFERENCES production.product_definition_revisions(organization_id,id,plant_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT fk_core_plants_current_plan_same_plant FOREIGN KEY (organization_id,current_plan_version_id,id) REFERENCES planning.plan_versions(organization_id,id,plant_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE planning.planning_state_heads
  ADD CONSTRAINT fk_planning_state_heads_revision_same_plant FOREIGN KEY (organization_id,current_revision_id,plant_id) REFERENCES planning.planning_state_revisions(organization_id,id,plant_id) ON DELETE RESTRICT;
ALTER TABLE planning.scenarios
  ADD CONSTRAINT fk_planning_scenarios_plan_same_plant FOREIGN KEY (organization_id,base_plan_version_id,plant_id) REFERENCES planning.plan_versions(organization_id,id,plant_id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_scenarios_state_same_plant FOREIGN KEY (organization_id,base_state_revision_id,plant_id) REFERENCES planning.planning_state_revisions(organization_id,id,plant_id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_scenarios_definition_same_plant FOREIGN KEY (organization_id,base_product_definition_revision_id,plant_id) REFERENCES production.product_definition_revisions(organization_id,id,plant_id) ON DELETE RESTRICT;
ALTER TABLE planning.plan_versions
  ADD CONSTRAINT fk_planning_plan_versions_definition_same_plant FOREIGN KEY (organization_id,product_definition_revision_id,plant_id) REFERENCES production.product_definition_revisions(organization_id,id,plant_id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_plan_versions_state_same_plant FOREIGN KEY (organization_id,planning_state_revision_id,plant_id) REFERENCES planning.planning_state_revisions(organization_id,id,plant_id) ON DELETE RESTRICT;

ALTER TABLE core.project_lots
  ADD CONSTRAINT fk_core_project_lots_hardware_event FOREIGN KEY (organization_id,hardware_source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT;
ALTER TABLE core.project_milestones
  ADD CONSTRAINT fk_core_project_milestones_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT;

ALTER TABLE capacity.overtime_authorizations
  ADD CONSTRAINT fk_capacity_overtime_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_capacity_overtime_scenario FOREIGN KEY (organization_id,scenario_id) REFERENCES planning.scenarios(organization_id,id) ON DELETE RESTRICT;
ALTER TABLE capacity.resource_unavailabilities
  ADD CONSTRAINT fk_capacity_unavailability_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT;

ALTER TABLE production.product_definition_revisions
  ADD CONSTRAINT fk_production_definition_revisions_scenario FOREIGN KEY (organization_id,source_scenario_id) REFERENCES planning.scenarios(organization_id,id) ON DELETE RESTRICT;
ALTER TABLE production.supplier_deliveries
  ADD CONSTRAINT fk_production_supplier_deliveries_event FOREIGN KEY (organization_id,effective_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT;
ALTER TABLE production.drawing_releases
  ADD CONSTRAINT fk_production_drawing_releases_event FOREIGN KEY (organization_id,effective_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT;
ALTER TABLE production.customer_availability_windows
  ADD CONSTRAINT fk_production_customer_windows_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT;

ALTER TABLE planning.planning_state_revisions
  ADD CONSTRAINT fk_planning_state_revisions_trigger FOREIGN KEY (organization_id,trigger_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE planning.manual_exceptions
  ADD CONSTRAINT fk_planning_manual_exceptions_hypothesis FOREIGN KEY (organization_id,source_hypothesis_id) REFERENCES planning.simulation_hypotheses(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE planning.plan_versions
  ADD CONSTRAINT fk_planning_plan_versions_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_plan_versions_scenario FOREIGN KEY (organization_id,source_scenario_id) REFERENCES planning.scenarios(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE planning.schedule_solutions
  ADD CONSTRAINT uq_planning_solutions_id_scenario UNIQUE (organization_id,id,scenario_id);
ALTER TABLE planning.plan_versions
  ADD CONSTRAINT fk_planning_plan_versions_solution_scenario FOREIGN KEY (organization_id,schedule_solution_id,source_scenario_id) REFERENCES planning.schedule_solutions(organization_id,id,scenario_id) ON DELETE RESTRICT;

ALTER TABLE planning.operation_plan_results
  ADD CONSTRAINT uq_planning_operation_results_id_solution UNIQUE (organization_id,id,schedule_solution_id);
ALTER TABLE planning.phase_plan_results
  ADD CONSTRAINT uq_planning_phase_results_id_solution UNIQUE (organization_id,id,schedule_solution_id),
  ADD CONSTRAINT fk_planning_phase_results_parent_solution FOREIGN KEY (organization_id,operation_plan_result_id,schedule_solution_id) REFERENCES planning.operation_plan_results(organization_id,id,schedule_solution_id) ON DELETE RESTRICT;
ALTER TABLE planning.planned_phase_assignments
  ADD CONSTRAINT uq_planning_phase_assignments_id_solution UNIQUE (organization_id,id,schedule_solution_id),
  ADD CONSTRAINT fk_planning_phase_assignments_result_solution FOREIGN KEY (organization_id,phase_plan_result_id,schedule_solution_id) REFERENCES planning.phase_plan_results(organization_id,id,schedule_solution_id) ON DELETE RESTRICT;
ALTER TABLE planning.assignment_segments
  ADD CONSTRAINT uq_planning_assignment_segments_id_solution UNIQUE (organization_id,id,schedule_solution_id),
  ADD CONSTRAINT fk_planning_assignment_segments_parent_solution FOREIGN KEY (organization_id,planned_phase_assignment_id,schedule_solution_id) REFERENCES planning.planned_phase_assignments(organization_id,id,schedule_solution_id) ON DELETE RESTRICT;
ALTER TABLE planning.human_segment_assignments
  ADD CONSTRAINT fk_planning_human_assignments_segment_solution FOREIGN KEY (organization_id,assignment_segment_id,schedule_solution_id) REFERENCES planning.assignment_segments(organization_id,id,schedule_solution_id) ON DELETE RESTRICT;
ALTER TABLE planning.physical_resource_reservations
  ADD CONSTRAINT fk_planning_resource_reservations_segment_solution FOREIGN KEY (organization_id,assignment_segment_id,schedule_solution_id) REFERENCES planning.assignment_segments(organization_id,id,schedule_solution_id) ON DELETE RESTRICT;
ALTER TABLE planning.operation_plan_results
  ADD CONSTRAINT fk_planning_operation_results_blocker FOREIGN KEY (organization_id,blocker_assignment_id) REFERENCES planning.planned_phase_assignments(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_operation_results_blocker_solution FOREIGN KEY (organization_id,blocker_assignment_id,schedule_solution_id) REFERENCES planning.planned_phase_assignments(organization_id,id,schedule_solution_id) ON DELETE RESTRICT;
ALTER TABLE planning.phase_plan_results
  ADD CONSTRAINT fk_planning_phase_results_remaining FOREIGN KEY (organization_id,remaining_estimate_revision_id) REFERENCES execution.remaining_estimate_revisions(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_phase_results_shared_assignment FOREIGN KEY (organization_id,shared_assignment_id) REFERENCES planning.planned_phase_assignments(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
  ADD CONSTRAINT fk_planning_phase_results_shared_solution FOREIGN KEY (organization_id,shared_assignment_id,schedule_solution_id) REFERENCES planning.planned_phase_assignments(organization_id,id,schedule_solution_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE planning.physical_occupations
  ADD CONSTRAINT fk_planning_occupations_execution FOREIGN KEY (organization_id,operation_execution_id) REFERENCES execution.operation_executions(organization_id,id) ON DELETE RESTRICT;
ALTER TABLE planning.planning_locks
  ADD CONSTRAINT fk_planning_locks_segment FOREIGN KEY (organization_id,assignment_segment_id) REFERENCES planning.assignment_segments(organization_id,id) ON DELETE RESTRICT,
  ADD CONSTRAINT fk_planning_locks_execution FOREIGN KEY (organization_id,source_execution_id) REFERENCES execution.operation_executions(organization_id,id) ON DELETE RESTRICT;

ALTER TABLE core.user_roles
  ADD CONSTRAINT ex_core_user_roles_no_overlap
  EXCLUDE USING gist (organization_id WITH =, user_profile_id WITH =, role_code WITH =, (COALESCE(plant_id,'00000000-0000-0000-0000-000000000000'::uuid)) WITH =, valid_during WITH &&);
ALTER TABLE capacity.employee_skills
  ADD CONSTRAINT ex_capacity_employee_skills_no_overlap
  EXCLUDE USING gist (organization_id WITH =, employee_id WITH =, skill_id WITH =, valid_during WITH &&) WHERE (enabled);
ALTER TABLE planning.plan_versions
  ADD CONSTRAINT ex_planning_plan_versions_validity
  EXCLUDE USING gist (organization_id WITH =, plant_id WITH =, valid_during WITH &&);
ALTER TABLE planning.human_segment_assignments
  ADD CONSTRAINT ex_planning_human_assignments_solution_employee
  EXCLUDE USING gist (organization_id WITH =, schedule_solution_id WITH =, employee_id WITH =, time_range WITH &&) WHERE (exclusive_guard);
ALTER TABLE planning.physical_resource_reservations
  ADD CONSTRAINT ex_planning_resource_reservations_solution_resource
  EXCLUDE USING gist (organization_id WITH =, schedule_solution_id WITH =, physical_resource_id WITH =, time_range WITH &&) WHERE (exclusive_guard);
ALTER TABLE planning.physical_occupations
  ADD CONSTRAINT ex_planning_occupations_planned
  EXCLUDE USING gist (organization_id WITH =, schedule_solution_id WITH =, physical_resource_id WITH =, time_range WITH &&) WHERE (source_kind='planned' AND is_effective),
  ADD CONSTRAINT ex_planning_occupations_actual
  EXCLUDE USING gist (organization_id WITH =, physical_resource_id WITH =, time_range WITH &&) WHERE (source_kind='actual' AND is_effective);

CREATE FUNCTION production.enforce_required_operation_lot_project() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
  IF NEW.project_lot_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM core.project_lots l
     WHERE l.organization_id=NEW.organization_id AND l.id=NEW.project_lot_id AND l.project_id=NEW.project_id
  ) THEN RAISE EXCEPTION 'project_lot_id does not belong to project_id' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_required_operation_lot_project
BEFORE INSERT OR UPDATE OF organization_id,project_id,project_lot_id ON production.required_operations
FOR EACH ROW EXECUTE FUNCTION production.enforce_required_operation_lot_project();

CREATE FUNCTION production.enforce_installation_operation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE operation_id uuid;
BEGIN
  operation_id := NEW.installation_operation_id;
  IF NOT EXISTS (
    SELECT 1 FROM production.required_operations o
     WHERE o.organization_id=NEW.organization_id AND o.id=operation_id AND o.operation_kind='installation'
  ) THEN RAISE EXCEPTION 'installation_operation_id must reference an installation operation' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_installation_coverages_operation_kind
BEFORE INSERT OR UPDATE OF organization_id,installation_operation_id ON production.installation_lot_coverages
FOR EACH ROW EXECUTE FUNCTION production.enforce_installation_operation();
CREATE TRIGGER trg_customer_windows_operation_kind
BEFORE INSERT OR UPDATE OF organization_id,installation_operation_id ON production.customer_availability_windows
FOR EACH ROW EXECUTE FUNCTION production.enforce_installation_operation();

CREATE FUNCTION execution.enforce_actual_usage_work_segment() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM execution.execution_segments s
     WHERE s.organization_id=NEW.organization_id AND s.id=NEW.execution_segment_id AND s.segment_kind='work'
  ) THEN RAISE EXCEPTION 'actual resource usage requires a work segment' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_actual_usage_work_segment
BEFORE INSERT OR UPDATE OF organization_id,execution_segment_id ON execution.actual_resource_usages
FOR EACH ROW EXECUTE FUNCTION execution.enforce_actual_usage_work_segment();

CREATE FUNCTION planning.enforce_solution_scenario_bases() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM planning.scenarios s
     WHERE s.organization_id=NEW.organization_id AND s.id=NEW.scenario_id
       AND s.base_state_revision_id=NEW.base_state_revision_id
       AND s.base_product_definition_revision_id=NEW.input_product_definition_revision_id
  ) THEN RAISE EXCEPTION 'solution revisions must match scenario bases' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_solution_scenario_bases
BEFORE INSERT OR UPDATE OF organization_id,scenario_id,base_state_revision_id,input_product_definition_revision_id ON planning.schedule_solutions
FOR EACH ROW EXECUTE FUNCTION planning.enforce_solution_scenario_bases();

CREATE INDEX ix01_core_projects_active_priority_commitment ON core.projects (organization_id,plant_id,priority_id,committed_date,id) WHERE status='active';
CREATE INDEX ix02_core_project_lots_project_sequence ON core.project_lots (organization_id,project_id,sequence_no);
CREATE INDEX ix03_production_operations_lot_status ON production.required_operations (organization_id,project_lot_id,status);
CREATE INDEX ix04_production_phases_pending ON production.required_operation_phases (organization_id,status,earliest_start_at) WHERE status IN ('draft','active');
CREATE INDEX ix05_production_precedences_predecessor_successor ON production.operation_precedences (organization_id,predecessor_operation_id,successor_operation_id) WHERE active;
CREATE INDEX ix06_production_gates_target_timing ON production.operation_gates (organization_id,gate_type,timing,required_operation_id);
CREATE INDEX ix07_production_material_pending ON production.material_requirements (organization_id,project_lot_id,needed_at) WHERE status='active';
CREATE INDEX ix08_production_allocations_requirement ON production.material_allocations (organization_id,material_requirement_id,supplier_delivery_line_id);
CREATE INDEX ix09_capacity_employees_center_status ON capacity.employees (organization_id,default_work_center_id,status);
CREATE INDEX ix10_capacity_resources_center_type_status ON capacity.physical_resources (organization_id,work_center_id,resource_type_id,status);
CREATE INDEX ix11_capacity_unavailability_employee_range ON capacity.resource_unavailabilities USING gist (organization_id,employee_id,time_range) WHERE employee_id IS NOT NULL;
CREATE INDEX ix12_capacity_calendar_exceptions_date ON capacity.calendar_exceptions (organization_id,calendar_id,exception_date);
CREATE INDEX ix13_planning_scenarios_base_status ON planning.scenarios (organization_id,plant_id,base_plan_version_id,status);
CREATE INDEX ix14_planning_scenarios_stale_candidates ON planning.scenarios (organization_id,plant_id,base_state_revision_id,base_product_definition_revision_id) WHERE status IN ('calculating','ready');
CREATE INDEX ix15_planning_solutions_scenario_status ON planning.schedule_solutions (organization_id,scenario_id,run_no,status);
CREATE INDEX ix16_planning_results_blocked_resource ON planning.operation_plan_results (organization_id,schedule_solution_id,critical_resource_id) WHERE result_status='blocked';
CREATE INDEX ix17_planning_segments_range ON planning.assignment_segments USING gist (time_range);
CREATE INDEX ix18_planning_human_employee_start ON planning.human_segment_assignments (organization_id,employee_id,lower(time_range));
CREATE INDEX ix19_planning_reservations_resource_start ON planning.physical_resource_reservations (organization_id,physical_resource_id,lower(time_range));
CREATE INDEX ix20_planning_occupations_active_resource ON planning.physical_occupations (organization_id,physical_resource_id,lower(time_range)) WHERE is_effective;
CREATE INDEX ix21_execution_active_operations ON execution.operation_executions (organization_id,required_operation_id,status,started_at) WHERE status IN ('running','paused');
CREATE INDEX ix22_execution_segments_range ON execution.execution_segments USING gist (time_range);
CREATE INDEX ix23_execution_usages_employee_range ON execution.actual_resource_usages USING gist (organization_id,employee_id,time_range) WHERE employee_id IS NOT NULL;
CREATE INDEX ix24_execution_remaining_current_lookup ON execution.remaining_estimate_revisions (organization_id,operation_execution_id,cutoff_at DESC) WHERE superseded_at IS NULL;
CREATE INDEX ix25_planning_events_entity_effective ON planning.effective_events (organization_id,entity_type,entity_id,effective_at DESC);
CREATE INDEX ix26_portal_tracking_hash_status ON portal.public_tracking_links (token_hash,status);
CREATE INDEX ix27_integration_queue_work ON integration.outbox_messages (status,available_at,id) WHERE status IN ('pending','failed');
CREATE INDEX ix28_audit_entity_actor_time ON audit.audit_entries (organization_id,entity_type,entity_id,actor_user_id,occurred_at DESC);

REVOKE ALL ON ALL TABLES IN SCHEMA core, capacity, production, planning, execution, portal, integration, audit FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA core, capacity, production, planning, execution, portal, integration, audit FROM PUBLIC;

COMMIT;
