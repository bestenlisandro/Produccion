BEGIN;

CREATE TABLE portal.public_stage_definitions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, code text NOT NULL, name text NOT NULL,
    sequence_no smallint NOT NULL, default_weight numeric(12,6), display_copy jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_final boolean NOT NULL DEFAULT false, status core.record_status NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_portal_stage_definitions_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_stage_definitions_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_portal_stage_definitions_code UNIQUE (organization_id,code),
    CONSTRAINT uq_portal_stage_definitions_sequence UNIQUE (organization_id,sequence_no),
    CONSTRAINT ck_portal_stage_definitions_sequence CHECK (sequence_no > 0),
    CONSTRAINT ck_portal_stage_definitions_weight CHECK (default_weight IS NULL OR default_weight >= 0),
    CONSTRAINT ck_portal_stage_definitions_copy CHECK (jsonb_typeof(display_copy)='object')
);

CREATE TABLE portal.public_stage_mapping_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, code text NOT NULL, version_no bigint NOT NULL,
    status text NOT NULL DEFAULT 'draft', published_at timestamptz, published_by uuid, supersedes_id uuid, description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_portal_mapping_sets_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_mapping_sets_publisher FOREIGN KEY (organization_id,published_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_mapping_sets_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES portal.public_stage_mapping_sets(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_mapping_sets_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_portal_mapping_sets_version UNIQUE (organization_id,code,version_no),
    CONSTRAINT ck_portal_mapping_sets_version CHECK (version_no > 0),
    CONSTRAINT ck_portal_mapping_sets_status CHECK (status IN ('draft','published','retired'))
);

CREATE TABLE portal.public_stage_mapping_rules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, mapping_set_id uuid NOT NULL,
    rule_no smallint NOT NULL, public_stage_definition_id uuid NOT NULL, predicate_type text NOT NULL,
    predicate jsonb NOT NULL, priority smallint NOT NULL, stop_on_match boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_portal_mapping_rules_set FOREIGN KEY (organization_id,mapping_set_id) REFERENCES portal.public_stage_mapping_sets(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_mapping_rules_stage FOREIGN KEY (organization_id,public_stage_definition_id) REFERENCES portal.public_stage_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_mapping_rules_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_portal_mapping_rules_number UNIQUE (organization_id,mapping_set_id,rule_no),
    CONSTRAINT uq_portal_mapping_rules_priority UNIQUE (organization_id,mapping_set_id,priority),
    CONSTRAINT ck_portal_mapping_rules_values CHECK (rule_no > 0 AND priority > 0 AND jsonb_typeof(predicate)='object')
);

CREATE TABLE portal.public_tracking_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL,
    token_hash bytea NOT NULL, status portal.public_link_status NOT NULL DEFAULT 'active', activated_at timestamptz NOT NULL,
    expires_at timestamptz, revoked_at timestamptz, revoked_by uuid, replaced_by_id uuid, last_accessed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_portal_tracking_links_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_tracking_links_revoker FOREIGN KEY (organization_id,revoked_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_tracking_links_replaced_by FOREIGN KEY (organization_id,replaced_by_id) REFERENCES portal.public_tracking_links(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_tracking_links_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_portal_tracking_links_hash UNIQUE (token_hash),
    CONSTRAINT ck_portal_tracking_links_hash CHECK (octet_length(token_hash)=32),
    CONSTRAINT ck_portal_tracking_links_expiry CHECK (expires_at IS NULL OR expires_at > activated_at)
);
CREATE UNIQUE INDEX ux_portal_tracking_links_one_active ON portal.public_tracking_links (organization_id,project_id) WHERE status='active';

CREATE TABLE portal.public_project_projections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL,
    source_plan_version_id uuid, mapping_set_id uuid NOT NULL, mapping_rule_id uuid NOT NULL, public_stage_id uuid NOT NULL,
    display_name text NOT NULL, progress_percent numeric(5,2), installation_percent numeric(5,2), communicated_date date,
    public_notice text, allowed_payload jsonb NOT NULL DEFAULT '{}'::jsonb, published_at timestamptz NOT NULL, published_by uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_portal_projections_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_projections_plan FOREIGN KEY (organization_id,source_plan_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_projections_mapping_set FOREIGN KEY (organization_id,mapping_set_id) REFERENCES portal.public_stage_mapping_sets(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_projections_mapping_rule FOREIGN KEY (organization_id,mapping_rule_id) REFERENCES portal.public_stage_mapping_rules(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_projections_stage FOREIGN KEY (organization_id,public_stage_id) REFERENCES portal.public_stage_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_projections_publisher FOREIGN KEY (organization_id,published_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_projections_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_portal_projections_project UNIQUE (organization_id,project_id),
    CONSTRAINT ck_portal_projections_progress CHECK ((progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100) AND (installation_percent IS NULL OR installation_percent BETWEEN 0 AND 100)),
    CONSTRAINT ck_portal_projections_payload CHECK (jsonb_typeof(allowed_payload)='object')
);

CREATE TABLE portal.public_timeline_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL, title text NOT NULL, body text, public_stage_id uuid, visibility_status text NOT NULL DEFAULT 'draft',
    published_at timestamptz, published_by uuid, source_event_id uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_portal_timeline_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_timeline_stage FOREIGN KEY (organization_id,public_stage_id) REFERENCES portal.public_stage_definitions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_timeline_publisher FOREIGN KEY (organization_id,published_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_timeline_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_timeline_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES portal.public_timeline_entries(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_timeline_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_portal_timeline_visibility CHECK (visibility_status IN ('draft','published','withdrawn'))
);

CREATE TABLE portal.communicated_dates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, project_id uuid NOT NULL,
    date_kind text NOT NULL, communicated_date date NOT NULL, source_plan_version_id uuid, approved_by uuid NOT NULL,
    communicated_at timestamptz NOT NULL, channel text, supersedes_id uuid, reason text, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_portal_communicated_dates_project FOREIGN KEY (organization_id,project_id) REFERENCES core.projects(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_communicated_dates_plan FOREIGN KEY (organization_id,source_plan_version_id) REFERENCES planning.plan_versions(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_communicated_dates_approver FOREIGN KEY (organization_id,approved_by) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_portal_communicated_dates_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES portal.communicated_dates(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_portal_communicated_dates_org_id UNIQUE (organization_id,id)
);

COMMIT;
