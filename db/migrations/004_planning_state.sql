BEGIN;

CREATE TABLE planning.planning_state_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    revision_no bigint NOT NULL, reason text NOT NULL, trigger_event_id uuid, transaction_key uuid NOT NULL,
    change_summary jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), created_by uuid,
    CONSTRAINT fk_planning_state_revisions_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_state_revisions_creator FOREIGN KEY (organization_id,created_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_state_revisions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_state_revisions_number UNIQUE (organization_id,plant_id,revision_no),
    CONSTRAINT uq_planning_state_revisions_transaction UNIQUE (organization_id,transaction_key),
    CONSTRAINT ck_planning_state_revisions_number CHECK (revision_no > 0),
    CONSTRAINT ck_planning_state_revisions_summary CHECK (jsonb_typeof(change_summary)='object')
);

CREATE TABLE planning.effective_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    event_type_code text NOT NULL, payload_schema_version smallint NOT NULL, occurred_at timestamptz NOT NULL, effective_at timestamptz NOT NULL,
    entity_type text NOT NULL, entity_id uuid NOT NULL, payload jsonb NOT NULL, cause text, planning_state_revision_id uuid,
    source_system text NOT NULL, external_reference text, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(), created_by uuid,
    CONSTRAINT fk_planning_effective_events_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_effective_events_revision FOREIGN KEY (organization_id,planning_state_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_effective_events_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_effective_events_creator FOREIGN KEY (organization_id,created_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_effective_events_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_planning_effective_events_schema_version CHECK (payload_schema_version > 0),
    CONSTRAINT ck_planning_effective_events_payload CHECK (jsonb_typeof(payload)='object')
);
CREATE UNIQUE INDEX ux_planning_effective_events_external ON planning.effective_events (organization_id,source_system,external_reference) WHERE external_reference IS NOT NULL;

CREATE TABLE planning.planning_state_heads (
    plant_id uuid PRIMARY KEY, organization_id uuid NOT NULL, current_revision_id uuid NOT NULL, current_revision_no bigint NOT NULL,
    row_version bigint NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now(), updated_by uuid,
    CONSTRAINT fk_planning_state_heads_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_state_heads_revision FOREIGN KEY (organization_id,current_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_state_heads_user FOREIGN KEY (organization_id,updated_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_state_heads_org_id UNIQUE (organization_id,plant_id),
    CONSTRAINT ck_planning_state_heads_revision_no CHECK (current_revision_no > 0)
);

CREATE TABLE planning.plan_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL, version_no bigint NOT NULL,
    schedule_solution_id uuid NOT NULL, product_definition_revision_id uuid NOT NULL, planning_state_revision_id uuid NOT NULL,
    previous_version_id uuid, source_scenario_id uuid NOT NULL, status text NOT NULL, valid_during tstzrange NOT NULL,
    confirmed_at timestamptz NOT NULL, confirmed_by uuid NOT NULL, reason text, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_plan_versions_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_plan_versions_definition FOREIGN KEY (organization_id,product_definition_revision_id) REFERENCES production.product_definition_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_plan_versions_state FOREIGN KEY (organization_id,planning_state_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_plan_versions_previous FOREIGN KEY (organization_id,previous_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_plan_versions_confirmer FOREIGN KEY (organization_id,confirmed_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_plan_versions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_plan_versions_number UNIQUE (organization_id,plant_id,version_no),
    CONSTRAINT ck_planning_plan_versions_number CHECK (version_no > 0),
    CONSTRAINT ck_planning_plan_versions_status CHECK (status IN ('published','superseded')),
    CONSTRAINT ck_planning_plan_versions_range CHECK (NOT isempty(valid_during) AND lower_inc(valid_during) AND NOT upper_inc(valid_during))
);

CREATE TABLE planning.scenarios (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    scenario_kind text NOT NULL, base_plan_version_id uuid, base_state_revision_id uuid NOT NULL, base_product_definition_revision_id uuid NOT NULL,
    trigger_event_id uuid, code text NOT NULL, name text NOT NULL, status planning.scenario_status NOT NULL DEFAULT 'draft',
    horizon_days smallint NOT NULL DEFAULT 90, horizon_range tstzrange NOT NULL, parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    requested_by uuid NOT NULL, started_at timestamptz, completed_at timestamptz, rejected_at timestamptz, rejection_reason text,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_planning_scenarios_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_scenarios_base_plan FOREIGN KEY (organization_id,base_plan_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_scenarios_base_state FOREIGN KEY (organization_id,base_state_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_scenarios_base_definition FOREIGN KEY (organization_id,base_product_definition_revision_id) REFERENCES production.product_definition_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_scenarios_trigger FOREIGN KEY (organization_id,trigger_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_scenarios_requester FOREIGN KEY (organization_id,requested_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_scenarios_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_scenarios_plant_code UNIQUE (organization_id,plant_id,code),
    CONSTRAINT ck_planning_scenarios_base CHECK ((scenario_kind='initial' AND base_plan_version_id IS NULL) OR (scenario_kind<>'initial' AND base_plan_version_id IS NOT NULL)),
    CONSTRAINT ck_planning_scenarios_horizon CHECK (horizon_days > 0 AND NOT isempty(horizon_range) AND lower_inc(horizon_range) AND NOT upper_inc(horizon_range)),
    CONSTRAINT ck_planning_scenarios_parameters CHECK (jsonb_typeof(parameters)='object')
);

CREATE TABLE planning.manual_exceptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    reason_code text NOT NULL, reason_text text NOT NULL, scenario_id uuid, project_id uuid, required_operation_id uuid,
    required_operation_phase_id uuid, employee_id uuid, physical_resource_id uuid, work_center_id uuid, time_range tstzrange,
    exception_kind text NOT NULL, parameters jsonb NOT NULL DEFAULT '{}'::jsonb, approved_by uuid NOT NULL, approved_at timestamptz NOT NULL,
    revoked_at timestamptz, revoked_by uuid, source_hypothesis_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_manual_exceptions_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_scenario FOREIGN KEY (organization_id,scenario_id) REFERENCES planning.scenarios(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_operation FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_center FOREIGN KEY (organization_id,work_center_id) REFERENCES capacity.work_centers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_approver FOREIGN KEY (organization_id,approved_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_manual_exceptions_revoker FOREIGN KEY (organization_id,revoked_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_manual_exceptions_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_planning_manual_exceptions_scope CHECK (project_id IS NOT NULL OR required_operation_id IS NOT NULL OR required_operation_phase_id IS NOT NULL OR employee_id IS NOT NULL OR physical_resource_id IS NOT NULL OR work_center_id IS NOT NULL),
    CONSTRAINT ck_planning_manual_exceptions_range CHECK (time_range IS NULL OR (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range))),
    CONSTRAINT ck_planning_manual_exceptions_parameters CHECK (jsonb_typeof(parameters)='object')
);

CREATE TABLE planning.simulation_hypotheses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, scenario_id uuid NOT NULL, hypothesis_no smallint NOT NULL,
    hypothesis_type text NOT NULL, target_type text NOT NULL, target_id uuid, parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    description text NOT NULL, source_revision_id uuid, source_event_id uuid, materialized_exception_id uuid, materialized_event_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_hypotheses_scenario FOREIGN KEY (organization_id,scenario_id) REFERENCES planning.scenarios(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_hypotheses_source_revision FOREIGN KEY (organization_id,source_revision_id) REFERENCES planning.planning_state_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_hypotheses_source_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_hypotheses_exception FOREIGN KEY (organization_id,materialized_exception_id) REFERENCES planning.manual_exceptions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_hypotheses_event FOREIGN KEY (organization_id,materialized_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_hypotheses_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_planning_hypotheses_number UNIQUE (organization_id,scenario_id,hypothesis_no),
    CONSTRAINT ck_planning_hypotheses_number CHECK (hypothesis_no > 0),
    CONSTRAINT ck_planning_hypotheses_parameters CHECK (jsonb_typeof(parameters)='object')
);

CREATE TABLE planning.planning_locks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    required_operation_id uuid, required_operation_phase_id uuid, plan_version_id uuid, assignment_segment_id uuid,
    employee_id uuid, physical_resource_id uuid, lock_scope text NOT NULL, valid_during tstzrange, reason text NOT NULL,
    source_execution_id uuid, released_at timestamptz, released_by uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_planning_locks_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_locks_operation FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_locks_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_locks_plan_version FOREIGN KEY (organization_id,plan_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_locks_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_locks_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_planning_locks_releaser FOREIGN KEY (organization_id,released_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_planning_locks_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_planning_locks_scope CHECK (required_operation_id IS NOT NULL OR required_operation_phase_id IS NOT NULL OR plan_version_id IS NOT NULL OR assignment_segment_id IS NOT NULL OR employee_id IS NOT NULL OR physical_resource_id IS NOT NULL),
    CONSTRAINT ck_planning_locks_range CHECK (valid_during IS NULL OR NOT isempty(valid_during))
);

COMMIT;
