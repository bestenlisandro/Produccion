BEGIN;

CREATE TABLE planning.schedule_solutions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, scenario_id uuid NOT NULL, run_no bigint NOT NULL,
    status planning.solution_status NOT NULL DEFAULT 'calculating', algorithm_version text NOT NULL,
    input_product_definition_revision_id uuid NOT NULL, base_state_revision_id uuid NOT NULL, input_snapshot jsonb NOT NULL,
    input_sha256 bytea NOT NULL, parameters jsonb NOT NULL DEFAULT '{}'::jsonb, started_at timestamptz NOT NULL, finished_at timestamptz,
    diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb, horizon_range tstzrange NOT NULL, solution_sha256 bytea, metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    ready_at timestamptz, failed_reason text, baseline_solution_id uuid, impact_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    comparison jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_solutions_scenario FOREIGN KEY (organization_id,scenario_id) REFERENCES planning.scenarios(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_solutions_definition FOREIGN KEY (organization_id,input_product_definition_revision_id) REFERENCES production.product_definition_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_solutions_state FOREIGN KEY (organization_id,base_state_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_solutions_baseline FOREIGN KEY (organization_id,baseline_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_solutions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_solutions_run UNIQUE (organization_id,scenario_id,run_no),
    CONSTRAINT ck_planning_solutions_run CHECK (run_no > 0),
    CONSTRAINT ck_planning_solutions_input_hash CHECK (octet_length(input_sha256)=32),
    CONSTRAINT ck_planning_solutions_solution_hash CHECK (solution_sha256 IS NULL OR octet_length(solution_sha256)=32),
    CONSTRAINT ck_planning_solutions_json CHECK (jsonb_typeof(input_snapshot)='object' AND jsonb_typeof(parameters)='object' AND jsonb_typeof(diagnostics)='object' AND jsonb_typeof(metrics)='object' AND jsonb_typeof(impact_summary)='object' AND jsonb_typeof(comparison)='object'),
    CONSTRAINT ck_planning_solutions_horizon CHECK (NOT isempty(horizon_range) AND lower_inc(horizon_range) AND NOT upper_inc(horizon_range)),
    CONSTRAINT ck_planning_solutions_terminal CHECK ((status='ready' AND solution_sha256 IS NOT NULL AND ready_at IS NOT NULL AND failed_reason IS NULL) OR (status='failed' AND failed_reason IS NOT NULL) OR status='calculating')
);

CREATE TABLE planning.impact_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, schedule_solution_id uuid NOT NULL,
    project_id uuid, required_operation_id uuid, required_operation_phase_id uuid, employee_id uuid, physical_resource_id uuid,
    milestone_definition_id uuid, impact_kind text NOT NULL, delta_minutes bigint, old_value jsonb, new_value jsonb, reason jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_impact_items_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_impact_items_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_impact_items_operation FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_impact_items_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_impact_items_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_impact_items_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_impact_items_milestone FOREIGN KEY (organization_id,milestone_definition_id) REFERENCES core.milestone_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_impact_items_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_planning_impact_items_target CHECK (project_id IS NOT NULL OR required_operation_id IS NOT NULL OR required_operation_phase_id IS NOT NULL OR employee_id IS NOT NULL OR physical_resource_id IS NOT NULL OR milestone_definition_id IS NOT NULL),
    CONSTRAINT ck_planning_impact_items_reason CHECK (jsonb_typeof(reason)='object')
);

CREATE TABLE planning.operation_plan_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, schedule_solution_id uuid NOT NULL,
    required_operation_id uuid NOT NULL, result_status planning.plan_result_status NOT NULL, planned_start_at timestamptz,
    planned_end_at timestamptz, remaining_work_minutes bigint, explanation jsonb NOT NULL DEFAULT '{}'::jsonb,
    critical_resource_id uuid, blocker_assignment_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_operation_results_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_operation_results_operation FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_operation_results_resource FOREIGN KEY (organization_id,critical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_operation_results_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_operation_results_operation UNIQUE (organization_id,schedule_solution_id,required_operation_id),
    CONSTRAINT ck_planning_operation_results_times CHECK (planned_start_at IS NULL OR planned_end_at IS NULL OR planned_start_at < planned_end_at),
    CONSTRAINT ck_planning_operation_results_remaining CHECK (remaining_work_minutes IS NULL OR remaining_work_minutes >= 0),
    CONSTRAINT ck_planning_operation_results_explanation CHECK (jsonb_typeof(explanation)='object')
);

CREATE TABLE planning.phase_plan_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, operation_plan_result_id uuid NOT NULL,
    schedule_solution_id uuid NOT NULL, required_operation_phase_id uuid NOT NULL, result_status planning.plan_result_status NOT NULL,
    remaining_estimate_revision_id uuid, shared_assignment_id uuid, planned_work_minutes bigint, remaining_work_minutes bigint,
    explanation jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_phase_results_operation_result FOREIGN KEY (organization_id,operation_plan_result_id) REFERENCES planning.operation_plan_results(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_phase_results_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_phase_results_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_phase_results_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_phase_results_phase UNIQUE (organization_id,schedule_solution_id,required_operation_phase_id),
    CONSTRAINT ck_planning_phase_results_minutes CHECK ((planned_work_minutes IS NULL OR planned_work_minutes >= 0) AND (remaining_work_minutes IS NULL OR remaining_work_minutes >= 0)),
    CONSTRAINT ck_planning_phase_results_explanation CHECK (jsonb_typeof(explanation)='object')
);

CREATE TABLE planning.planned_phase_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, phase_plan_result_id uuid,
    production_batch_version_id uuid, schedule_solution_id uuid NOT NULL, assignment_kind text NOT NULL,
    planned_start_at timestamptz NOT NULL, planned_end_at timestamptz NOT NULL, work_minutes bigint NOT NULL,
    status text NOT NULL DEFAULT 'planned', created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_phase_assignments_phase_result FOREIGN KEY (organization_id,phase_plan_result_id) REFERENCES planning.phase_plan_results(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_phase_assignments_batch FOREIGN KEY (organization_id,production_batch_version_id) REFERENCES production.production_batch_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_phase_assignments_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_phase_assignments_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_planning_phase_assignments_owner CHECK ((phase_plan_result_id IS NOT NULL)::int + (production_batch_version_id IS NOT NULL)::int = 1),
    CONSTRAINT ck_planning_phase_assignments_time CHECK (planned_start_at < planned_end_at),
    CONSTRAINT ck_planning_phase_assignments_work CHECK (work_minutes >= 0)
);

CREATE TABLE planning.assignment_segments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, planned_phase_assignment_id uuid NOT NULL,
    schedule_solution_id uuid NOT NULL, segment_no smallint NOT NULL, time_range tstzrange NOT NULL,
    normal_minutes bigint NOT NULL, overtime_minutes bigint NOT NULL DEFAULT 0, work_minutes bigint NOT NULL,
    status text NOT NULL DEFAULT 'planned', created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_assignment_segments_assignment FOREIGN KEY (organization_id,planned_phase_assignment_id) REFERENCES planning.planned_phase_assignments(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_assignment_segments_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_assignment_segments_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_assignment_segments_number UNIQUE (organization_id,planned_phase_assignment_id,segment_no),
    CONSTRAINT ck_planning_assignment_segments_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)),
    CONSTRAINT ck_planning_assignment_segments_minutes CHECK (segment_no > 0 AND normal_minutes >= 0 AND overtime_minutes >= 0 AND work_minutes >= 0 AND work_minutes = normal_minutes + overtime_minutes)
);

CREATE TABLE planning.human_segment_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, assignment_segment_id uuid NOT NULL,
    schedule_solution_id uuid NOT NULL, employee_id uuid NOT NULL, time_range tstzrange NOT NULL,
    normal_minutes bigint NOT NULL, overtime_minutes bigint NOT NULL DEFAULT 0, work_minutes bigint NOT NULL,
    overtime_authorization_id uuid, exclusive_guard boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_human_assignments_segment FOREIGN KEY (organization_id,assignment_segment_id) REFERENCES planning.assignment_segments(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_human_assignments_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_human_assignments_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_human_assignments_overtime FOREIGN KEY (organization_id,overtime_authorization_id) REFERENCES capacity.overtime_authorizations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_human_assignments_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_human_assignments_segment_employee UNIQUE (organization_id,assignment_segment_id,employee_id),
    CONSTRAINT ck_planning_human_assignments_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)),
    CONSTRAINT ck_planning_human_assignments_minutes CHECK (normal_minutes >= 0 AND overtime_minutes >= 0 AND work_minutes = normal_minutes + overtime_minutes)
);

CREATE TABLE planning.physical_resource_reservations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, assignment_segment_id uuid NOT NULL,
    schedule_solution_id uuid NOT NULL, physical_resource_id uuid NOT NULL, time_range tstzrange NOT NULL,
    capacity_units numeric(12,4) NOT NULL, exclusive_guard boolean NOT NULL, usage_mode text NOT NULL,
    overtime_authorization_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_resource_reservations_segment FOREIGN KEY (organization_id,assignment_segment_id) REFERENCES planning.assignment_segments(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_resource_reservations_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_resource_reservations_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_resource_reservations_overtime FOREIGN KEY (organization_id,overtime_authorization_id) REFERENCES capacity.overtime_authorizations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_resource_reservations_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_resource_reservations_segment_resource UNIQUE (organization_id,assignment_segment_id,physical_resource_id),
    CONSTRAINT ck_planning_resource_reservations_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)),
    CONSTRAINT ck_planning_resource_reservations_capacity CHECK (capacity_units > 0),
    CONSTRAINT ck_planning_resource_reservations_mode CHECK (usage_mode IN ('active_use','occupation'))
);

CREATE TABLE planning.physical_occupations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, schedule_solution_id uuid, operation_execution_id uuid,
    project_lot_id uuid NOT NULL, required_operation_phase_id uuid, physical_resource_id uuid NOT NULL, source_kind text NOT NULL,
    time_range tstzrange NOT NULL, planned_release_at timestamptz, actual_released_at timestamptz, release_event_id uuid,
    supersedes_id uuid, is_effective boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_occupations_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_occupations_lot FOREIGN KEY (organization_id,project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_occupations_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_occupations_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_occupations_event FOREIGN KEY (organization_id,release_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_occupations_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES planning.physical_occupations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_occupations_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_planning_occupations_source CHECK ((source_kind='planned' AND schedule_solution_id IS NOT NULL AND operation_execution_id IS NULL) OR (source_kind='actual' AND schedule_solution_id IS NULL AND operation_execution_id IS NOT NULL)),
    CONSTRAINT ck_planning_occupations_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range))
);

CREATE TABLE planning.solution_milestones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, schedule_solution_id uuid NOT NULL,
    project_id uuid NOT NULL, milestone_definition_id uuid NOT NULL, estimated_at timestamptz NOT NULL,
    critical_path jsonb, confidence_metadata jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_solution_milestones_solution FOREIGN KEY (organization_id,schedule_solution_id) REFERENCES planning.schedule_solutions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_solution_milestones_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_solution_milestones_definition FOREIGN KEY (organization_id,milestone_definition_id) REFERENCES core.milestone_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_solution_milestones_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_solution_milestones_target UNIQUE (organization_id,schedule_solution_id,project_id,milestone_definition_id),
    CONSTRAINT ck_planning_solution_milestones_confidence CHECK (jsonb_typeof(confidence_metadata)='object')
);

COMMIT;
