#!/bin/sh
# Creates the secrets Docker Compose needs, in ./secrets. Existing files are
# never overwritten: losing the master key makes saved API keys unreadable.
set -eu

dir="$(cd "$(dirname "$0")/.." && pwd)/secrets"
mkdir -p "$dir"
chmod 700 "$dir"

random_hex() { head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

write() {
    if [ -e "$dir/$1" ]; then
        echo "kept    secrets/$1"
        return
    fi
    # World-readable so the container users can read it; the directory is
    # private to you on the host.
    (umask 022 && printf '%s' "$2" >"$dir/$1")
    echo "created secrets/$1"
}

write postgres_admin_password "$(random_hex 24)"
write postgres_owner_password "$(random_hex 24)"
write postgres_app_password "$(random_hex 24)"
write openchart_master_key "$(head -c 32 /dev/urandom | base64 | tr -d '\n')"

owner=$(cat "$dir/postgres_owner_password")
app=$(cat "$dir/postgres_app_password")
write openchart_migrate_database_url "postgresql+asyncpg://openchart_owner:$owner@postgres:5432/openchart"
write openchart_database_url "postgresql+asyncpg://openchart_app:$app@postgres:5432/openchart"

echo "Back up secrets/openchart_master_key somewhere safe."
