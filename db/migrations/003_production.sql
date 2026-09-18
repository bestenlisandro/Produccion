BEGIN;

CREATE TABLE core.projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL, customer_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, description text, commercial_owner_id uuid, priority_id uuid NOT NULL,
    status core.record_status NOT NULL DEFAULT 'draft', accepted_on date, desired_start_at timestamptz, committed_date date, closed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_projects_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_projects_customer FOREIGN KEY (organization_id,customer_id) REFERENCES core.customers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_projects_owner FOREIGN KEY (organization_id,commercial_owner_id) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_projects_priority FOREIGN KEY (organization_id,priority_id) REFERENCES core.project_priorities(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_projects_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_core_projects_org_code UNIQUE (organization_id,code)
);

CREATE TABLE core.project_lots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, description text, sequence_no smallint NOT NULL, quantity numeric(14,4), unit text,
    status core.record_status NOT NULL DEFAULT 'draft', hardware_status text NOT NULL DEFAULT 'unknown', hardware_available_at timestamptz, hardware_source_event_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_project_lots_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_project_lots_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_core_project_lots_project_code UNIQUE (organization_id,project_id,code),
    CONSTRAINT uq_core_project_lots_project_sequence UNIQUE (organization_id,project_id,sequence_no),
    CONSTRAINT ck_core_project_lots_sequence CHECK (sequence_no > 0),
    CONSTRAINT ck_core_project_lots_quantity CHECK (quantity IS NULL OR quantity > 0),
    CONSTRAINT ck_core_project_lots_hardware_status CHECK (hardware_status IN ('unknown','pending','partial','ready','not_required'))
);

CREATE TABLE production.operation_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, category text NOT NULL, default_estimate_unit text NOT NULL DEFAULT 'minute',
    default_split_policy text NOT NULL DEFAULT 'splittable', description text, is_system boolean NOT NULL DEFAULT false,
    status core.record_status NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_operation_definitions_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_operation_definitions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_operation_definitions_org_code UNIQUE (organization_id,code),
    CONSTRAINT ck_production_operation_definitions_split CHECK (default_split_policy IN ('non_splittable','splittable','continuous'))
);

CREATE TABLE production.route_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, description text, status core.record_status NOT NULL DEFAULT 'draft',
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_route_templates_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_templates_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_route_templates_org_code UNIQUE (organization_id,code)
);

CREATE TABLE production.route_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_template_id uuid NOT NULL,
    version_no bigint NOT NULL, status text NOT NULL DEFAULT 'draft', published_at timestamptz, published_by uuid, supersedes_id uuid, notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_route_versions_template FOREIGN KEY (organization_id,route_template_id) REFERENCES production.route_templates(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_versions_publisher FOREIGN KEY (organization_id,published_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_versions_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES production.route_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_versions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_route_versions_number UNIQUE (organization_id,route_template_id,version_no),
    CONSTRAINT ck_production_route_versions_number CHECK (version_no > 0),
    CONSTRAINT ck_production_route_versions_status CHECK (status IN ('draft','published','retired'))
);

CREATE TABLE production.route_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_version_id uuid NOT NULL, operation_definition_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, sequence_hint smallint, settings jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_route_steps_version FOREIGN KEY (organization_id,route_version_id) REFERENCES production.route_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_steps_definition FOREIGN KEY (organization_id,operation_definition_id) REFERENCES production.operation_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_steps_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_route_steps_version_code UNIQUE (organization_id,route_version_id,code),
    CONSTRAINT ck_production_route_steps_settings CHECK (jsonb_typeof(settings)='object')
);

CREATE TABLE production.route_step_phase_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_step_id uuid NOT NULL,
    sequence_no smallint NOT NULL, code text NOT NULL, name text NOT NULL, estimate_kind text NOT NULL,
    original_estimate_minutes bigint NOT NULL, split_policy text NOT NULL, min_team smallint, max_team smallint,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_phase_templates_step FOREIGN KEY (organization_id,route_step_id) REFERENCES production.route_steps(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_phase_templates_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_phase_templates_sequence UNIQUE (organization_id,route_step_id,sequence_no),
    CONSTRAINT uq_production_phase_templates_code UNIQUE (organization_id,route_step_id,code),
    CONSTRAINT ck_production_phase_templates_estimate CHECK (original_estimate_minutes >= 0),
    CONSTRAINT ck_production_phase_templates_team CHECK (min_team IS NULL OR (min_team > 0 AND max_team >= min_team)),
    CONSTRAINT ck_production_phase_templates_split CHECK (split_policy IN ('non_splittable','splittable','continuous'))
);

CREATE TABLE production.route_step_precedences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_version_id uuid NOT NULL,
    predecessor_step_id uuid NOT NULL, successor_step_id uuid NOT NULL, precedence_type text NOT NULL DEFAULT 'finish_start', lag_minutes bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_route_precedences_version FOREIGN KEY (organization_id,route_version_id) REFERENCES production.route_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_precedences_predecessor FOREIGN KEY (organization_id,predecessor_step_id) REFERENCES production.route_steps(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_precedences_successor FOREIGN KEY (organization_id,successor_step_id) REFERENCES production.route_steps(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_precedences_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_route_precedences_edge UNIQUE (organization_id,route_version_id,predecessor_step_id,successor_step_id,precedence_type),
    CONSTRAINT ck_production_route_precedences_not_self CHECK (predecessor_step_id <> successor_step_id),
    CONSTRAINT ck_production_route_precedences_type CHECK (precedence_type IN ('finish_start','start_start','finish_finish'))
);

CREATE TABLE production.lot_route_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_lot_id uuid NOT NULL, route_version_id uuid NOT NULL,
    valid_during tstzrange NOT NULL, is_active boolean NOT NULL DEFAULT true, assigned_by uuid NOT NULL, reason text, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_lot_routes_lot FOREIGN KEY (organization_id,project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_lot_routes_version FOREIGN KEY (organization_id,route_version_id) REFERENCES production.route_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_lot_routes_assigner FOREIGN KEY (organization_id,assigned_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_lot_routes_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_lot_routes_range CHECK (NOT isempty(valid_during) AND lower_inc(valid_during) AND NOT upper_inc(valid_during))
);
CREATE UNIQUE INDEX ux_production_lot_routes_one_active ON production.lot_route_assignments (organization_id,project_lot_id) WHERE is_active;

CREATE TABLE production.required_operations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL, project_lot_id uuid,
    operation_definition_id uuid NOT NULL, route_step_id uuid, operation_kind production.operation_kind NOT NULL DEFAULT 'production',
    code text NOT NULL, name text NOT NULL, status core.record_status NOT NULL DEFAULT 'draft', earliest_start_at timestamptz, cancelled_at timestamptz,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_required_operations_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_required_operations_lot FOREIGN KEY (organization_id,project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_required_operations_definition FOREIGN KEY (organization_id,operation_definition_id) REFERENCES production.operation_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_required_operations_route_step FOREIGN KEY (organization_id,route_step_id) REFERENCES production.route_steps(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_required_operations_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_required_operations_code UNIQUE NULLS NOT DISTINCT (organization_id,project_id,project_lot_id,code),
    CONSTRAINT ck_production_required_operations_settings CHECK (jsonb_typeof(settings)='object')
);

CREATE TABLE production.required_operation_phases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, required_operation_id uuid NOT NULL, route_step_phase_template_id uuid,
    sequence_no smallint NOT NULL, code text NOT NULL, name text NOT NULL, estimate_kind text NOT NULL, original_estimate_minutes bigint NOT NULL,
    split_policy text NOT NULL, status core.record_status NOT NULL DEFAULT 'draft', earliest_start_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_required_phases_operation FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_required_phases_template FOREIGN KEY (organization_id,route_step_phase_template_id) REFERENCES production.route_step_phase_templates(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_required_phases_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_required_phases_sequence UNIQUE (organization_id,required_operation_id,sequence_no),
    CONSTRAINT uq_production_required_phases_code UNIQUE (organization_id,required_operation_id,code),
    CONSTRAINT ck_production_required_phases_estimate CHECK (original_estimate_minutes >= 0),
    CONSTRAINT ck_production_required_phases_split CHECK (split_policy IN ('non_splittable','splittable','continuous'))
);

CREATE TABLE production.operation_precedences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, predecessor_operation_id uuid NOT NULL, successor_operation_id uuid NOT NULL,
    precedence_type text NOT NULL DEFAULT 'finish_start', lag_minutes bigint NOT NULL DEFAULT 0, source text NOT NULL, active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_operation_precedences_predecessor FOREIGN KEY (organization_id,predecessor_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_operation_precedences_successor FOREIGN KEY (organization_id,successor_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_operation_precedences_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_operation_precedences_not_self CHECK (predecessor_operation_id <> successor_operation_id),
    CONSTRAINT ck_production_operation_precedences_type CHECK (precedence_type IN ('finish_start','start_start','finish_finish'))
);
CREATE UNIQUE INDEX ux_production_operation_precedences_active_edge ON production.operation_precedences (organization_id,predecessor_operation_id,successor_operation_id,precedence_type) WHERE active;

CREATE TABLE production.operation_labor_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, required_operation_phase_id uuid NOT NULL, skill_id uuid NOT NULL,
    min_people smallint NOT NULL, max_people smallint NOT NULL, work_minutes bigint NOT NULL, productivity_curve jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_mandatory boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_labor_requirements_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_labor_requirements_skill FOREIGN KEY (organization_id,skill_id) REFERENCES capacity.skills(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_labor_requirements_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_labor_requirements_team CHECK (min_people >= 1 AND max_people >= min_people),
    CONSTRAINT ck_production_labor_requirements_work CHECK (work_minutes >= 0),
    CONSTRAINT ck_production_labor_requirements_curve CHECK (jsonb_typeof(productivity_curve)='object')
);

CREATE TABLE production.operation_physical_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, required_operation_phase_id uuid NOT NULL,
    physical_resource_type_id uuid, physical_resource_group_id uuid, work_center_id uuid,
    quantity numeric(12,4) NOT NULL, capacity_units numeric(12,4) NOT NULL, is_mandatory boolean NOT NULL DEFAULT true, usage_mode text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_physical_requirements_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_physical_requirements_type FOREIGN KEY (organization_id,physical_resource_type_id) REFERENCES capacity.physical_resource_types(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_physical_requirements_group FOREIGN KEY (organization_id,physical_resource_group_id) REFERENCES capacity.physical_resource_groups(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_physical_requirements_center FOREIGN KEY (organization_id,work_center_id) REFERENCES capacity.work_centers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_physical_requirements_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_physical_requirements_selector CHECK (physical_resource_type_id IS NOT NULL OR physical_resource_group_id IS NOT NULL OR work_center_id IS NOT NULL),
    CONSTRAINT ck_production_physical_requirements_values CHECK (quantity > 0 AND capacity_units > 0),
    CONSTRAINT ck_production_physical_requirements_mode CHECK (usage_mode IN ('active_use','occupation'))
);

CREATE TABLE production.product_definition_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    revision_no bigint NOT NULL, parent_revision_id uuid, source_scenario_id uuid, snapshot_schema_version smallint NOT NULL,
    canonicalization_version smallint NOT NULL, canonical_snapshot jsonb NOT NULL, snapshot_sha256 bytea NOT NULL, reason text,
    created_at timestamptz NOT NULL DEFAULT now(), created_by uuid,
    CONSTRAINT fk_production_definition_revisions_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_definition_revisions_parent FOREIGN KEY (organization_id,parent_revision_id) REFERENCES production.product_definition_revisions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_definition_revisions_creator FOREIGN KEY (organization_id,created_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_definition_revisions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_definition_revisions_number UNIQUE (organization_id,plant_id,revision_no),
    CONSTRAINT uq_production_definition_revisions_hash UNIQUE (organization_id,plant_id,snapshot_sha256),
    CONSTRAINT ck_production_definition_revisions_number CHECK (revision_no > 0),
    CONSTRAINT ck_production_definition_revisions_versions CHECK (snapshot_schema_version > 0 AND canonicalization_version > 0),
    CONSTRAINT ck_production_definition_revisions_snapshot CHECK (jsonb_typeof(canonical_snapshot)='object'),
    CONSTRAINT ck_production_definition_revisions_hash CHECK (octet_length(snapshot_sha256)=32)
);

CREATE TABLE production.production_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL, code text NOT NULL, name text NOT NULL,
    operation_definition_id uuid NOT NULL, status core.record_status NOT NULL DEFAULT 'draft', description text,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_batches_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_batches_definition FOREIGN KEY (organization_id,operation_definition_id) REFERENCES production.operation_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_batches_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_batches_plant_code UNIQUE (organization_id,plant_id,code)
);

CREATE TABLE production.production_batch_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, production_batch_id uuid NOT NULL,
    version_no bigint NOT NULL, status text NOT NULL DEFAULT 'draft', manual_estimate_minutes bigint NOT NULL,
    published_at timestamptz, published_by uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_batch_versions_batch FOREIGN KEY (organization_id,production_batch_id) REFERENCES production.production_batches(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_batch_versions_publisher FOREIGN KEY (organization_id,published_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_batch_versions_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES production.production_batch_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_batch_versions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_batch_versions_number UNIQUE (organization_id,production_batch_id,version_no),
    CONSTRAINT ck_production_batch_versions_values CHECK (version_no > 0 AND manual_estimate_minutes >= 0),
    CONSTRAINT ck_production_batch_versions_status CHECK (status IN ('draft','published','retired'))
);

CREATE TABLE production.production_batch_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, production_batch_version_id uuid NOT NULL,
    required_operation_phase_id uuid NOT NULL, allocation_factor numeric(12,6), sequence_hint smallint, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_batch_members_version FOREIGN KEY (organization_id,production_batch_version_id) REFERENCES production.production_batch_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_batch_members_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_batch_members_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_batch_members_phase UNIQUE (organization_id,production_batch_version_id,required_operation_phase_id),
    CONSTRAINT ck_production_batch_members_factor CHECK (allocation_factor IS NULL OR allocation_factor > 0)
);

CREATE TABLE production.suppliers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, code text NOT NULL, name text NOT NULL,
    external_reference text, source_system text NOT NULL DEFAULT 'production', status core.record_status NOT NULL DEFAULT 'active', contact jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_suppliers_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_suppliers_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_suppliers_org_code UNIQUE (organization_id,code),
    CONSTRAINT ck_production_suppliers_contact CHECK (jsonb_typeof(contact)='object')
);
CREATE UNIQUE INDEX ux_production_suppliers_external ON production.suppliers (organization_id,source_system,external_reference) WHERE external_reference IS NOT NULL;

CREATE TABLE production.material_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_lot_id uuid NOT NULL,
    code text NOT NULL, description text NOT NULL, required_quantity numeric(14,4) NOT NULL, unit text NOT NULL,
    is_mandatory boolean NOT NULL DEFAULT true, needed_at timestamptz, status core.record_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_material_requirements_lot FOREIGN KEY (organization_id,project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_material_requirements_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_material_requirements_lot_code UNIQUE (organization_id,project_lot_id,code),
    CONSTRAINT ck_production_material_requirements_quantity CHECK (required_quantity > 0)
);

CREATE TABLE production.supplier_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, supplier_id uuid NOT NULL, project_id uuid,
    order_number text, status core.record_status NOT NULL DEFAULT 'draft', ordered_at timestamptz, promised_at timestamptz,
    source_system text NOT NULL DEFAULT 'production', external_reference text, revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_supplier_orders_supplier FOREIGN KEY (organization_id,supplier_id) REFERENCES production.suppliers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_supplier_orders_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_supplier_orders_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_supplier_orders_revision CHECK (revision > 0)
);
CREATE UNIQUE INDEX ux_production_supplier_orders_external ON production.supplier_orders (organization_id,source_system,external_reference) WHERE external_reference IS NOT NULL;

CREATE TABLE production.supplier_order_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, supplier_order_id uuid NOT NULL,
    line_no smallint NOT NULL, material_code text NOT NULL, description text NOT NULL, ordered_quantity numeric(14,4) NOT NULL,
    unit text NOT NULL, promised_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_supplier_order_lines_order FOREIGN KEY (organization_id,supplier_order_id) REFERENCES production.supplier_orders(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_supplier_order_lines_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_supplier_order_lines_number UNIQUE (organization_id,supplier_order_id,line_no),
    CONSTRAINT ck_production_supplier_order_lines_values CHECK (line_no > 0 AND ordered_quantity > 0)
);

CREATE TABLE production.supplier_deliveries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, supplier_order_id uuid, supplier_id uuid NOT NULL,
    delivered_at timestamptz NOT NULL, delivery_kind text NOT NULL, source_system text NOT NULL, external_reference text,
    effective_event_id uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_supplier_deliveries_order FOREIGN KEY (organization_id,supplier_order_id) REFERENCES production.supplier_orders(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_supplier_deliveries_supplier FOREIGN KEY (organization_id,supplier_id) REFERENCES production.suppliers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_supplier_deliveries_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES production.supplier_deliveries(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_supplier_deliveries_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_supplier_deliveries_kind CHECK (delivery_kind IN ('receipt','return','correction'))
);
CREATE UNIQUE INDEX ux_production_supplier_deliveries_external ON production.supplier_deliveries (organization_id,source_system,external_reference) WHERE external_reference IS NOT NULL;

CREATE TABLE production.supplier_delivery_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, supplier_delivery_id uuid NOT NULL, supplier_order_line_id uuid,
    line_no smallint NOT NULL, material_code text NOT NULL, quantity numeric(14,4) NOT NULL, unit text NOT NULL, movement_sign smallint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_delivery_lines_delivery FOREIGN KEY (organization_id,supplier_delivery_id) REFERENCES production.supplier_deliveries(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_delivery_lines_order_line FOREIGN KEY (organization_id,supplier_order_line_id) REFERENCES production.supplier_order_lines(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_delivery_lines_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_delivery_lines_number UNIQUE (organization_id,supplier_delivery_id,line_no),
    CONSTRAINT ck_production_delivery_lines_values CHECK (line_no > 0 AND quantity > 0 AND movement_sign IN (-1,1))
);

CREATE TABLE production.material_allocations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, supplier_delivery_line_id uuid NOT NULL, material_requirement_id uuid NOT NULL,
    quantity numeric(14,4) NOT NULL, unit text NOT NULL, movement_sign smallint NOT NULL, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_material_allocations_delivery_line FOREIGN KEY (organization_id,supplier_delivery_line_id) REFERENCES production.supplier_delivery_lines(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_material_allocations_requirement FOREIGN KEY (organization_id,material_requirement_id) REFERENCES production.material_requirements(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_material_allocations_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES production.material_allocations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_material_allocations_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_material_allocations_values CHECK (quantity > 0 AND movement_sign IN (-1,1))
);

CREATE TABLE production.drawing_packages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_lot_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, status core.record_status NOT NULL DEFAULT 'draft', required boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_drawing_packages_lot FOREIGN KEY (organization_id,project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_drawing_packages_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_drawing_packages_lot_code UNIQUE (organization_id,project_lot_id,code)
);

CREATE TABLE production.drawing_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, drawing_package_id uuid NOT NULL,
    release_no bigint NOT NULL, status text NOT NULL, released_at timestamptz, released_by uuid, document_reference text,
    supersedes_id uuid, effective_event_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_drawing_releases_package FOREIGN KEY (organization_id,drawing_package_id) REFERENCES production.drawing_packages(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_drawing_releases_user FOREIGN KEY (organization_id,released_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_drawing_releases_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES production.drawing_releases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_drawing_releases_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_drawing_releases_number UNIQUE (organization_id,drawing_package_id,release_no),
    CONSTRAINT ck_production_drawing_releases_number CHECK (release_no > 0),
    CONSTRAINT ck_production_drawing_releases_status CHECK (status IN ('draft','released','withdrawn'))
);

CREATE TABLE production.installation_lot_coverages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, installation_operation_id uuid NOT NULL, project_lot_id uuid NOT NULL,
    coverage_percent numeric(5,2), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_installation_coverages_operation FOREIGN KEY (organization_id,installation_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_installation_coverages_lot FOREIGN KEY (organization_id,project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_installation_coverages_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_production_installation_coverages_pair UNIQUE (organization_id,installation_operation_id,project_lot_id),
    CONSTRAINT ck_production_installation_coverages_percent CHECK (coverage_percent IS NULL OR coverage_percent BETWEEN 0 AND 100)
);

CREATE TABLE production.customer_availability_windows (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, installation_operation_id uuid NOT NULL,
    time_range tstzrange NOT NULL, mandatory boolean NOT NULL DEFAULT true, source text NOT NULL, notes text, source_event_id uuid, supersedes_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_customer_windows_operation FOREIGN KEY (organization_id,installation_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_customer_windows_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES production.customer_availability_windows(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_customer_windows_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_customer_windows_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range))
);

CREATE TABLE production.route_phase_labor_requirement_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_step_phase_template_id uuid NOT NULL, skill_id uuid NOT NULL,
    min_people smallint NOT NULL, max_people smallint NOT NULL, work_minutes bigint NOT NULL, productivity_curve jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_mandatory boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_route_labor_templates_phase FOREIGN KEY (organization_id,route_step_phase_template_id) REFERENCES production.route_step_phase_templates(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_labor_templates_skill FOREIGN KEY (organization_id,skill_id) REFERENCES capacity.skills(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_labor_templates_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_route_labor_templates_team CHECK (min_people >= 1 AND max_people >= min_people),
    CONSTRAINT ck_production_route_labor_templates_work CHECK (work_minutes >= 0)
);

CREATE TABLE production.route_phase_physical_requirement_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_step_phase_template_id uuid NOT NULL,
    physical_resource_type_id uuid, physical_resource_group_id uuid, work_center_id uuid, quantity numeric(12,4) NOT NULL,
    capacity_units numeric(12,4) NOT NULL, usage_mode text NOT NULL, is_mandatory boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_route_physical_templates_phase FOREIGN KEY (organization_id,route_step_phase_template_id) REFERENCES production.route_step_phase_templates(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_physical_templates_type FOREIGN KEY (organization_id,physical_resource_type_id) REFERENCES capacity.physical_resource_types(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_physical_templates_group FOREIGN KEY (organization_id,physical_resource_group_id) REFERENCES capacity.physical_resource_groups(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_route_physical_templates_center FOREIGN KEY (organization_id,work_center_id) REFERENCES capacity.work_centers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_physical_templates_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_route_physical_templates_selector CHECK (physical_resource_type_id IS NOT NULL OR physical_resource_group_id IS NOT NULL OR work_center_id IS NOT NULL),
    CONSTRAINT ck_production_route_physical_templates_values CHECK (quantity > 0 AND capacity_units > 0),
    CONSTRAINT ck_production_route_physical_templates_mode CHECK (usage_mode IN ('active_use','occupation'))
);

CREATE TABLE production.route_phase_gate_templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, route_step_phase_template_id uuid NOT NULL,
    timing text NOT NULL, gate_type text NOT NULL, target_kind text NOT NULL, parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_mandatory boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_production_route_gate_templates_phase FOREIGN KEY (organization_id,route_step_phase_template_id) REFERENCES production.route_step_phase_templates(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_route_gate_templates_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_route_gate_templates_timing CHECK (timing IN ('before_start','before_finish')),
    CONSTRAINT ck_production_route_gate_templates_parameters CHECK (jsonb_typeof(parameters)='object')
);

CREATE TABLE production.operation_gates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, required_operation_id uuid NOT NULL, required_operation_phase_id uuid,
    timing text NOT NULL, gate_type text NOT NULL, material_requirement_id uuid, drawing_package_id uuid, hardware_project_lot_id uuid,
    milestone_definition_id uuid, available_at timestamptz, config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_production_operation_gates_operation FOREIGN KEY (organization_id,required_operation_id) REFERENCES production.required_operations(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_operation_gates_phase FOREIGN KEY (organization_id,required_operation_phase_id) REFERENCES production.required_operation_phases(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_operation_gates_material FOREIGN KEY (organization_id,material_requirement_id) REFERENCES production.material_requirements(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_operation_gates_drawing FOREIGN KEY (organization_id,drawing_package_id) REFERENCES production.drawing_packages(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_operation_gates_hardware_lot FOREIGN KEY (organization_id,hardware_project_lot_id) REFERENCES core.project_lots(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_production_operation_gates_milestone FOREIGN KEY (organization_id,milestone_definition_id) REFERENCES core.milestone_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_production_operation_gates_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_production_operation_gates_timing CHECK (timing IN ('before_start','before_finish')),
    CONSTRAINT ck_production_operation_gates_target CHECK ((material_requirement_id IS NOT NULL)::int + (drawing_package_id IS NOT NULL)::int + (hardware_project_lot_id IS NOT NULL)::int + (milestone_definition_id IS NOT NULL)::int + (available_at IS NOT NULL)::int = 1),
    CONSTRAINT ck_production_operation_gates_config CHECK (jsonb_typeof(config)='object')
);

CREATE TABLE core.project_milestones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL, milestone_definition_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL, source_event_id uuid, notes text, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_core_project_milestones_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_project_milestones_definition FOREIGN KEY (organization_id,milestone_definition_id) REFERENCES core.milestone_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_project_milestones_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES core.project_milestones(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_project_milestones_org_id UNIQUE (organization_id,id)
);

COMMIT;
