BEGIN;

CREATE TABLE execution.operation_executions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, required_operation_id uuid NOT NULL,
    source_product_definition_revision_id uuid NOT NULL, original_estimate_snapshot jsonb NOT NULL,
    status execution.execution_status NOT NULL DEFAULT 'not_started', origin_plan_version_id uuid, origin_operation_plan_result_id uuid,
    started_at timestamptz, paused_at timestamptz, completed_at timestamptz, cancelled_at timestamptz,
    remaining_state text, source_event_id uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(), created_by uuid,
    CONSTRAINT fk_execution_operations_required FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_operations_definition FOREIGN KEY (organization_id,source_product_definition_revision_id) REFERENCES production.product_definition_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_operations_plan FOREIGN KEY (organization_id,origin_plan_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_operations_result FOREIGN KEY (organization_id,origin_operation_plan_result_id) REFERENCES planning.operation_plan_results(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_operations_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_operations_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES execution.operation_executions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_operations_creator FOREIGN KEY (organization_id,created_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_execution_operations_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_execution_operations_snapshot CHECK (jsonb_typeof(original_estimate_snapshot)='object')
);

CREATE TABLE execution.execution_segments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, operation_execution_id uuid NOT NULL,
    required_operation_phase_id uuid, origin_assignment_segment_id uuid, segment_no bigint NOT NULL,
    time_range tstzrange NOT NULL, segment_kind execution.segment_kind NOT NULL, work_minutes bigint NOT NULL, reason text,
    source_event_id uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_execution_segments_execution FOREIGN KEY (organization_id,operation_execution_id) REFERENCES execution.operation_executions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_segments_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_segments_origin FOREIGN KEY (organization_id,origin_assignment_segment_id) REFERENCES planning.assignment_segments(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_segments_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_segments_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES execution.execution_segments(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_execution_segments_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_execution_segments_number UNIQUE (organization_id,operation_execution_id,segment_no),
    CONSTRAINT ck_execution_segments_number CHECK (segment_no > 0),
    CONSTRAINT ck_execution_segments_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)),
    CONSTRAINT ck_execution_segments_kind CHECK ((segment_kind='work' AND required_operation_phase_id IS NOT NULL AND work_minutes >= 0) OR (segment_kind='pause' AND work_minutes=0 AND reason IS NOT NULL))
);

CREATE TABLE execution.actual_resource_usages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, execution_segment_id uuid NOT NULL,
    employee_id uuid, physical_resource_id uuid, time_range tstzrange NOT NULL, work_minutes bigint NOT NULL,
    capacity_units numeric(12,4), usage_kind text NOT NULL, source_event_id uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_execution_resource_usages_segment FOREIGN KEY (organization_id,execution_segment_id) REFERENCES execution.execution_segments(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_resource_usages_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_resource_usages_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_resource_usages_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_resource_usages_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES execution.actual_resource_usages(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_execution_resource_usages_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_execution_resource_usages_owner CHECK ((employee_id IS NOT NULL)::int + (physical_resource_id IS NOT NULL)::int = 1),
    CONSTRAINT ck_execution_resource_usages_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)),
    CONSTRAINT ck_execution_resource_usages_values CHECK (work_minutes >= 0 AND (capacity_units IS NULL OR capacity_units > 0))
);

CREATE TABLE execution.remaining_estimate_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, operation_execution_id uuid NOT NULL,
    revision_no bigint NOT NULL, previous_revision_id uuid, cutoff_at timestamptz NOT NULL, input_mode text NOT NULL,
    raw_input jsonb NOT NULL, reason text, effective_event_id uuid NOT NULL, planning_state_revision_id uuid NOT NULL,
    executed_labor_minutes_at_cutoff bigint NOT NULL, remaining_labor_minutes bigint NOT NULL, updated_total_labor_minutes bigint NOT NULL,
    superseded_at timestamptz, superseded_by_id uuid, created_at timestamptz NOT NULL DEFAULT now(), created_by uuid,
    CONSTRAINT fk_execution_remaining_revisions_execution FOREIGN KEY (organization_id,operation_execution_id) REFERENCES execution.operation_executions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_revisions_previous FOREIGN KEY (organization_id,previous_revision_id) REFERENCES execution.remaining_estimate_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_revisions_event FOREIGN KEY (organization_id,effective_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_revisions_state FOREIGN KEY (organization_id,planning_state_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_revisions_superseded_by FOREIGN KEY (organization_id,superseded_by_id) REFERENCES execution.remaining_estimate_revisions(organization_id,id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_execution_remaining_revisions_creator FOREIGN KEY (organization_id,created_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_execution_remaining_revisions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_execution_remaining_revisions_number UNIQUE (organization_id,operation_execution_id,revision_no),
    CONSTRAINT ck_execution_remaining_revisions_number CHECK (revision_no > 0),
    CONSTRAINT ck_execution_remaining_revisions_mode CHECK (input_mode IN ('delta','remaining_duration','expected_finish')),
    CONSTRAINT ck_execution_remaining_revisions_input CHECK (jsonb_typeof(raw_input)='object'),
    CONSTRAINT ck_execution_remaining_revisions_values CHECK (executed_labor_minutes_at_cutoff >= 0 AND remaining_labor_minutes >= 0 AND updated_total_labor_minutes = executed_labor_minutes_at_cutoff + remaining_labor_minutes),
    CONSTRAINT ck_execution_remaining_revisions_superseding CHECK ((superseded_at IS NULL AND superseded_by_id IS NULL) OR (superseded_at IS NOT NULL AND superseded_by_id IS NOT NULL))
);
CREATE UNIQUE INDEX ux_execution_remaining_revisions_current ON execution.remaining_estimate_revisions (organization_id,operation_execution_id) WHERE superseded_at IS NULL;

CREATE TABLE execution.remaining_resource_estimates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, remaining_estimate_revision_id uuid NOT NULL,
    required_operation_phase_id uuid NOT NULL, dimension execution.remaining_dimension NOT NULL, skill_id uuid,
    min_people smallint, max_people smallint, physical_requirement_id uuid, physical_resource_id uuid,
    remaining_minutes bigint, expected_release_at timestamptz, capacity_units numeric(12,4), details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_execution_remaining_resources_revision FOREIGN KEY (organization_id,remaining_estimate_revision_id) REFERENCES execution.remaining_estimate_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_resources_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_resources_skill FOREIGN KEY (organization_id,skill_id) REFERENCES capacity.skills(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_resources_requirement FOREIGN KEY (organization_id,physical_requirement_id) REFERENCES production.operation_physical_requirements(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_execution_remaining_resources_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_execution_remaining_resources_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_execution_remaining_resources_values CHECK ((remaining_minutes IS NULL OR remaining_minutes >= 0) AND (capacity_units IS NULL OR capacity_units > 0)),
    CONSTRAINT ck_execution_remaining_resources_details CHECK (jsonb_typeof(details)='object'),
    CONSTRAINT ck_execution_remaining_resources_dimension CHECK (
      (dimension='LABOR_WORK' AND skill_id IS NOT NULL AND min_people >= 1 AND max_people >= min_people AND physical_requirement_id IS NULL AND expected_release_at IS NULL)
      OR (dimension='ACTIVE_PHYSICAL_USE' AND physical_requirement_id IS NOT NULL AND remaining_minutes IS NOT NULL AND skill_id IS NULL AND expected_release_at IS NULL)
      OR (dimension='PHYSICAL_OCCUPATION' AND physical_resource_id IS NOT NULL AND (remaining_minutes IS NOT NULL OR expected_release_at IS NOT NULL) AND skill_id IS NULL)
    )
);

COMMIT;
