BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS capacity;
CREATE SCHEMA IF NOT EXISTS production;
CREATE SCHEMA IF NOT EXISTS planning;
CREATE SCHEMA IF NOT EXISTS execution;
CREATE SCHEMA IF NOT EXISTS portal;
CREATE SCHEMA IF NOT EXISTS integration;
CREATE SCHEMA IF NOT EXISTS audit;

REVOKE ALL ON SCHEMA core, capacity, production, planning, execution, portal, integration, audit FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, capacity, production, planning, execution, portal, integration, audit REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, capacity, production, planning, execution, portal, integration, audit REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA core, capacity, production, planning, execution, portal, integration, audit REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TYPE core.record_status AS ENUM ('draft', 'active', 'inactive', 'archived');
CREATE TYPE core.app_role_code AS ENUM ('admin', 'planner', 'supervisor', 'operator', 'portal_service');
CREATE TYPE capacity.scheduling_mode AS ENUM ('exclusive', 'cumulative');
CREATE TYPE capacity.calendar_effect AS ENUM ('add', 'remove', 'replace');
CREATE TYPE production.operation_kind AS ENUM ('production', 'installation');
CREATE TYPE planning.scenario_status AS ENUM ('draft', 'calculating', 'ready', 'failed', 'rejected', 'confirmed', 'stale');
CREATE TYPE planning.solution_status AS ENUM ('calculating', 'ready', 'failed');
CREATE TYPE planning.plan_result_status AS ENUM ('planned', 'blocked', 'out_of_horizon', 'completed');
CREATE TYPE execution.execution_status AS ENUM ('not_started', 'running', 'paused', 'completed', 'cancelled');
CREATE TYPE execution.segment_kind AS ENUM ('work', 'pause');
CREATE TYPE execution.remaining_dimension AS ENUM ('LABOR_WORK', 'ACTIVE_PHYSICAL_USE', 'PHYSICAL_OCCUPATION');
CREATE TYPE portal.public_link_status AS ENUM ('active', 'revoked', 'expired');
CREATE TYPE integration.message_status AS ENUM ('pending', 'processing', 'processed', 'failed', 'published');

COMMIT;
