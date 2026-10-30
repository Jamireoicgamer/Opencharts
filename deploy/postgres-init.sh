#!/bin/sh
# Runs once, when the Postgres volume is first created. Creates the schema
# owner (used only by migrations) and the least-privilege role the API uses.
set -eu

owner_password=$(cat /run/secrets/postgres_owner_password)
app_password=$(cat /run/secrets/postgres_app_password)

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v owner_password="$owner_password" -v app_password="$app_password" <<'SQL'
CREATE ROLE openchart_owner LOGIN PASSWORD :'owner_password';
CREATE ROLE openchart_app LOGIN PASSWORD :'app_password';
ALTER DATABASE openchart OWNER TO openchart_owner;
REVOKE ALL ON DATABASE openchart FROM PUBLIC;
GRANT CONNECT ON DATABASE openchart TO openchart_app;
SQL
