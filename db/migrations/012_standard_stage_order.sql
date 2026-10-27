BEGIN;

-- Classification only: never a scheduling precedence or a capacity requirement.
ALTER TABLE production.operation_definitions
    ADD COLUMN display_order integer NOT NULL DEFAULT 1000,
    ADD CONSTRAINT ck_operation_definitions_display_order CHECK (display_order > 0);

COMMIT;
