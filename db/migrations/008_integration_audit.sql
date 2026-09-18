BEGIN;

CREATE TABLE integration.inbox_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, source_system text NOT NULL,
    idempotency_key text NOT NULL, message_type text NOT NULL, message_schema_version smallint NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL, payload_sha256 bytea NOT NULL,
    status integration.message_status NOT NULL DEFAULT 'pending', processed_at timestamptz, error jsonb, retry_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_integration_inbox_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_integration_inbox_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_integration_inbox_idempotency UNIQUE (organization_id,source_system,idempotency_key),
    CONSTRAINT ck_integration_inbox_schema CHECK (message_schema_version > 0),
    CONSTRAINT ck_integration_inbox_hash CHECK (octet_length(payload_sha256)=32),
    CONSTRAINT ck_integration_inbox_payload CHECK (jsonb_typeof(payload)='object'),
    CONSTRAINT ck_integration_inbox_retry CHECK (retry_count >= 0)
);

CREATE TABLE integration.outbox_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL, event_type text NOT NULL, event_schema_version smallint NOT NULL, logical_key text NOT NULL,
    payload jsonb NOT NULL, occurred_at timestamptz NOT NULL, available_at timestamptz NOT NULL,
    status integration.message_status NOT NULL DEFAULT 'pending', published_at timestamptz, retry_count integer NOT NULL DEFAULT 0, last_error jsonb,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), row_version bigint NOT NULL DEFAULT 1,
    CONSTRAINT fk_integration_outbox_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT uq_integration_outbox_org_id UNIQUE (organization_id,id),
    CONSTRAINT uq_integration_outbox_logical_key UNIQUE (organization_id,logical_key),
    CONSTRAINT ck_integration_outbox_schema CHECK (event_schema_version > 0),
    CONSTRAINT ck_integration_outbox_payload CHECK (jsonb_typeof(payload)='object'),
    CONSTRAINT ck_integration_outbox_retry CHECK (retry_count >= 0)
);

CREATE TABLE audit.audit_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), organization_id uuid NOT NULL, actor_user_id uuid,
    action_code text NOT NULL, entity_type text NOT NULL, entity_id uuid NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(),
    request_id uuid, transaction_key uuid, before_data jsonb, after_data jsonb, metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_event_id uuid, supersedes_id uuid, created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_audit_entries_org FOREIGN KEY (organization_id) REFERENCES core.organizations(id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_entries_actor FOREIGN KEY (organization_id,actor_user_id) REFERENCES core.user_profiles(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_entries_event FOREIGN KEY (organization_id,source_event_id) REFERENCES planning.effective_events(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT fk_audit_entries_supersedes FOREIGN KEY (organization_id,supersedes_id) REFERENCES audit.audit_entries(organization_id,id) ON DELETE RESTRICT,
    CONSTRAINT uq_audit_entries_org_id UNIQUE (organization_id,id),
    CONSTRAINT ck_audit_entries_json CHECK ((before_data IS NULL OR jsonb_typeof(before_data)='object') AND (after_data IS NULL OR jsonb_typeof(after_data)='object') AND jsonb_typeof(metadata)='object')
);

COMMIT;
