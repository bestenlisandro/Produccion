BEGIN;

CREATE TABLE capacity.calendars (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, timezone text NOT NULL, calendar_kind text NOT NULL, description text,
    status core.record_status NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_calendars_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_calendars_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_calendars_org_code UNIQUE (organization_id,code)
);

CREATE TABLE capacity.calendar_working_intervals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, calendar_id uuid NOT NULL,
    weekday smallint NOT NULL, local_start time NOT NULL, local_end time NOT NULL, shift_code text,
    capacity_factor numeric(12,6) NOT NULL DEFAULT 1, valid_during daterange NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_working_intervals_calendar FOREIGN KEY (organization_id,calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_working_intervals_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_capacity_working_intervals_weekday CHECK (weekday BETWEEN 1 AND 7),
    CONSTRAINT ck_capacity_working_intervals_time CHECK (local_start < local_end),
    CONSTRAINT ck_capacity_working_intervals_factor CHECK (capacity_factor > 0),
    CONSTRAINT ck_capacity_working_intervals_valid CHECK (NOT isempty(valid_during))
);

CREATE TABLE capacity.calendar_exceptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, calendar_id uuid NOT NULL,
    exception_date date NOT NULL, time_range tstzrange, effect capacity.calendar_effect NOT NULL, capacity_factor numeric(12,6), reason text,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_calendar_exceptions_calendar FOREIGN KEY (organization_id,calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_calendar_exceptions_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_capacity_calendar_exceptions_range CHECK (time_range IS NULL OR NOT isempty(time_range)),
    CONSTRAINT ck_capacity_calendar_exceptions_factor CHECK (capacity_factor IS NULL OR capacity_factor > 0)
);

CREATE TABLE capacity.work_centers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, capacity_mode capacity.scheduling_mode NOT NULL,
    aggregate_capacity numeric(12,4), capacity_unit text, base_calendar_id uuid,
    status core.record_status NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_work_centers_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_work_centers_calendar FOREIGN KEY (organization_id,base_calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_work_centers_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_work_centers_plant_code UNIQUE (organization_id,plant_id,code),
    CONSTRAINT ck_capacity_work_centers_aggregate CHECK (aggregate_capacity IS NULL OR aggregate_capacity > 0)
);

CREATE TABLE capacity.skills (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, description text, category text,
    status core.record_status NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_skills_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_skills_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_skills_org_code UNIQUE (organization_id,code)
);

CREATE TABLE capacity.employees (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    code text NOT NULL, display_name text NOT NULL, user_profile_id uuid, status core.record_status NOT NULL DEFAULT 'active',
    default_work_center_id uuid, base_calendar_id uuid NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_employees_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_employees_user FOREIGN KEY (organization_id,user_profile_id) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_employees_center FOREIGN KEY (organization_id,default_work_center_id) REFERENCES capacity.work_centers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_employees_calendar FOREIGN KEY (organization_id,base_calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_employees_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_employees_plant_code UNIQUE (organization_id,plant_id,code),
    CONSTRAINT uq_capacity_employees_user UNIQUE (organization_id,user_profile_id),
    CONSTRAINT ck_capacity_employees_metadata_object CHECK (jsonb_typeof(metadata)='object')
);

CREATE TABLE capacity.employee_skills (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, employee_id uuid NOT NULL, skill_id uuid NOT NULL,
    valid_during daterange NOT NULL, level numeric(6,3), enabled boolean NOT NULL DEFAULT true, approved_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_capacity_employee_skills_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_employee_skills_skill FOREIGN KEY (organization_id,skill_id) REFERENCES capacity.skills(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_employee_skills_approver FOREIGN KEY (organization_id,approved_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_employee_skills_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_capacity_employee_skills_valid CHECK (NOT isempty(valid_during))
);

CREATE TABLE capacity.physical_resource_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, resource_kind text NOT NULL, default_scheduling_mode capacity.scheduling_mode NOT NULL, default_capacity_unit text,
    status core.record_status NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_resource_types_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_resource_types_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_resource_types_org_code UNIQUE (organization_id,code)
);

CREATE TABLE capacity.physical_resources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL, work_center_id uuid NOT NULL,
    resource_type_id uuid NOT NULL, code text NOT NULL, name text NOT NULL, scheduling_mode capacity.scheduling_mode NOT NULL,
    capacity_units numeric(12,4) NOT NULL, capacity_unit text, status core.record_status NOT NULL DEFAULT 'active', is_mobile boolean NOT NULL DEFAULT false,
    base_calendar_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_resources_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_resources_center FOREIGN KEY (organization_id,work_center_id) REFERENCES capacity.work_centers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_resources_type FOREIGN KEY (organization_id,resource_type_id) REFERENCES capacity.physical_resource_types(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_resources_calendar FOREIGN KEY (organization_id,base_calendar_id) REFERENCES capacity.calendars(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_resources_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_resources_plant_code UNIQUE (organization_id,plant_id,code),
    CONSTRAINT ck_capacity_resources_units CHECK (capacity_units > 0)
);

CREATE TABLE capacity.physical_resource_groups (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    code text NOT NULL, name text NOT NULL, selection_policy text NOT NULL, description text,
    status core.record_status NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_resource_groups_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_resource_groups_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_resource_groups_plant_code UNIQUE (organization_id,plant_id,code)
);

CREATE TABLE capacity.physical_resource_group_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, group_id uuid NOT NULL, physical_resource_id uuid NOT NULL,
    valid_during daterange NOT NULL, priority smallint,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_capacity_group_members_group FOREIGN KEY (organization_id,group_id) REFERENCES capacity.physical_resource_groups(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_group_members_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_group_members_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_capacity_group_members_period UNIQUE (organization_id,group_id,physical_resource_id,valid_during),
    CONSTRAINT ck_capacity_group_members_valid CHECK (NOT isempty(valid_during))
);

CREATE TABLE capacity.resource_unavailabilities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, employee_id uuid, physical_resource_id uuid,
    time_range tstzrange NOT NULL, reason_code text NOT NULL, source_event_id uuid, supersedes_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_capacity_unavailability_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_unavailability_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_unavailability_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES capacity.resource_unavailabilities(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_unavailability_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_capacity_unavailability_owner CHECK ((employee_id IS NOT NULL)::int + (physical_resource_id IS NOT NULL)::int = 1),
    CONSTRAINT ck_capacity_unavailability_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range))
);

CREATE TABLE capacity.overtime_authorizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, plant_id uuid NOT NULL,
    project_id uuid, scenario_id uuid, employee_id uuid, physical_resource_id uuid, work_center_id uuid,
    time_range tstzrange NOT NULL, max_minutes bigint, approved_by uuid NOT NULL, reason text NOT NULL,
    revoked_at timestamptz, revoked_by uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_capacity_overtime_plant FOREIGN KEY (organization_id,plant_id) REFERENCES core.plants(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_overtime_employee FOREIGN KEY (organization_id,employee_id) REFERENCES capacity.employees(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_overtime_resource FOREIGN KEY (organization_id,physical_resource_id) REFERENCES capacity.physical_resources(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_overtime_center FOREIGN KEY (organization_id,work_center_id) REFERENCES capacity.work_centers(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_overtime_approver FOREIGN KEY (organization_id,approved_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_capacity_overtime_revoker FOREIGN KEY (organization_id,revoked_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_capacity_overtime_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_capacity_overtime_scope CHECK (project_id IS NOT NULL OR scenario_id IS NOT NULL OR employee_id IS NOT NULL OR physical_resource_id IS NOT NULL OR work_center_id IS NOT NULL),
    CONSTRAINT ck_capacity_overtime_range CHECK (NOT isempty(time_range) AND lower_inc(time_range) AND NOT upper_inc(time_range)),
    CONSTRAINT ck_capacity_overtime_minutes CHECK (max_minutes IS NULL OR max_minutes > 0)
);

COMMIT;
