BEGIN;

-- V1: one principal installation location per project; historical rows stay NULL.
ALTER TABLE core.projects
    ADD COLUMN installation_site_name text,
    ADD COLUMN installation_address text,
    ADD COLUMN installation_locality text,
    ADD COLUMN installation_contact_name text,
    ADD COLUMN installation_contact_phone text,
    ADD COLUMN installation_access_notes text;

COMMIT;
