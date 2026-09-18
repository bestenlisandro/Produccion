BEGIN;

CREATE TABLE core.organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL,
    legal_name text NOT NULL,
    display_name text NOT NULL,
    default_timezone text NOT NULL,
    status core.record_status NOT NULL DEFAULT 'active',
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT uq_core_organizations_slug UNIQUE (slug),
    CONSTRAINT ck_core_organizations_slug CHECK (slug = lower(slug) AND slug ~ '^[a-z0-9][a-z0-9-]*$'),
    CONSTRAINT ck_core_organizations_settings_object CHECK (jsonb_typeof(settings) = 'object')
);

CREATE TABLE core.user_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    auth_subject text NOT NULL,
    display_name text NOT NULL,
    email text,
    status core.record_status NOT NULL DEFAULT 'active',
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_user_profiles_organization FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_user_profiles_org_id UNIQUE (organization_id, id),
    CONSTRAINT uq_core_user_profiles_auth_subject UNIQUE (auth_subject)
);

CREATE TABLE core.plants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    timezone text NOT NULL,
    base_calendar_id uuid,
    communication_calendar_id uuid,
    communication_threshold_business_days smallint NOT NULL DEFAULT 1,
    current_product_definition_revision_id uuid,
    current_plan_version_id uuid,
    promotion_lock_version bigint NOT NULL DEFAULT 1,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    status core.record_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_plants_organization FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_plants_org_id UNIQUE (organization_id, id),
    CONSTRAINT uq_core_plants_org_code UNIQUE (organization_id, code),
    CONSTRAINT ck_core_plants_communication_threshold CHECK (communication_threshold_business_days >= 0),
    CONSTRAINT ck_core_plants_settings_object CHECK (jsonb_typeof(settings) = 'object')
);

CREATE TABLE core.user_roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    user_profile_id uuid NOT NULL,
    role_code core.app_role_code NOT NULL,
    plant_id uuid,
    valid_during daterange NOT NULL,
    assigned_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_user_roles_organization FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_user_roles_user FOREIGN KEY (organization_id, user_profile_id) REFERENCES core.user_profiles(organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_user_roles_plant FOREIGN KEY (organization_id, plant_id) REFERENCES core.plants(organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT fk_core_user_roles_assigned_by FOREIGN KEY (organization_id, assigned_by) REFERENCES core.user_profiles(organization_id, id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_user_roles_org_id UNIQUE (organization_id, id),
    CONSTRAINT ck_core_user_roles_valid_range CHECK (NOT isempty(valid_during))
);

CREATE TABLE core.customers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    code text,
    display_name text NOT NULL,
    email text,
    phone text,
    notes text,
    privacy_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status core.record_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_customers_organization FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_customers_org_id UNIQUE (organization_id, id),
    CONSTRAINT uq_core_customers_org_code UNIQUE (organization_id, code),
    CONSTRAINT ck_core_customers_privacy_object CHECK (jsonb_typeof(privacy_metadata) = 'object')
);

CREATE TABLE core.project_priorities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    rank smallint NOT NULL,
    color text,
    is_default boolean NOT NULL DEFAULT false,
    status core.record_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_project_priorities_organization FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_project_priorities_org_id UNIQUE (organization_id, id),
    CONSTRAINT uq_core_project_priorities_org_code UNIQUE (organization_id, code),
    CONSTRAINT uq_core_project_priorities_org_rank UNIQUE (organization_id, rank),
    CONSTRAINT ck_core_project_priorities_rank CHECK (rank > 0)
);
CREATE UNIQUE INDEX ux_core_project_priorities_one_default ON core.project_priorities (organization_id) WHERE is_default AND status = 'active';

CREATE TABLE core.milestone_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    category text NOT NULL,
    sequence_no smallint NOT NULL,
    is_system boolean NOT NULL DEFAULT false,
    status core.record_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_core_milestone_definitions_organization FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_core_milestone_definitions_org_id UNIQUE (organization_id, id),
    CONSTRAINT uq_core_milestone_definitions_org_code UNIQUE (organization_id, code),
    CONSTRAINT uq_core_milestone_definitions_org_sequence UNIQUE (organization_id, sequence_no),
    CONSTRAINT ck_core_milestone_definitions_sequence CHECK (sequence_no > 0)
);

COMMIT;
