-- Executed once by the postgres image on first initialization (dev/test only).
-- Production provisions these roles with real secrets via its own tooling (see docs/OPERATIONS.md).
-- nexscout_owner: owns the schema, runs migrations and admin tasks. BYPASSRLS because tables use
--                 FORCE ROW LEVEL SECURITY, which otherwise applies to the owner too.
-- nexscout_app:   runtime role used by api/worker. Not the owner and no BYPASSRLS, so RLS applies.
CREATE ROLE nexscout_owner LOGIN PASSWORD 'nexscout_owner_dev' CREATEDB BYPASSRLS;
CREATE ROLE nexscout_app LOGIN PASSWORD 'nexscout_app_dev' NOSUPERUSER NOBYPASSRLS;
-- nexscout_system: worker-only role for queue claiming/leases/recovery across tenants.
CREATE ROLE nexscout_system LOGIN PASSWORD 'nexscout_system_dev' NOSUPERUSER BYPASSRLS;

CREATE DATABASE nexscout OWNER nexscout_owner;
CREATE DATABASE nexscout_test OWNER nexscout_owner;

\connect nexscout
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO nexscout_owner;
GRANT USAGE ON SCHEMA public TO nexscout_app;
GRANT USAGE ON SCHEMA public TO nexscout_system;

\connect nexscout_test
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO nexscout_owner;
GRANT USAGE ON SCHEMA public TO nexscout_app;
GRANT USAGE ON SCHEMA public TO nexscout_system;
