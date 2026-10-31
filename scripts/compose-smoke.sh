#!/bin/sh
# Builds and starts the Docker Compose stack, checks it end to end, then
# removes it again (including its database volume). Used by CI.
set -eu
cd "$(dirname "$0")/.."

base="http://127.0.0.1:${OPENCHART_PORT:-8080}"
jar=$(mktemp)

fail() {
    echo "FAILED: $1" >&2
    docker compose ps >&2
    docker compose logs --no-color >&2
    exit 1
}

cleanup() {
    rm -f "$jar"
    docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

sh scripts/gen-secrets.sh
docker compose up -d --build

tries=0
until curl -sf "$base/api/health" >/dev/null; do
    tries=$((tries + 1))
    [ "$tries" -le 90 ] || fail "stack did not become healthy"
    sleep 2
done
echo "health: $(curl -s "$base/api/health")"

curl -s "$base/api/setup/status" | grep -q '"needs_setup":true' || fail "fresh install should need setup"

headers=$(curl -sI "$base/")
echo "$headers" | grep -qi "content-security-policy: default-src 'self'" || fail "missing CSP header"
echo "$headers" | grep -qi "x-content-type-options: nosniff" || fail "missing nosniff header"
curl -sf "$base/account/keys" | grep -q '<div id="root">' || fail "SPA routes should serve index.html"

token=$(docker compose logs api 2>&1 | sed -n 's/.*setup token: \([A-Za-z0-9_-]*\).*/\1/p' | tail -n 1)
[ -n "$token" ] || fail "setup token not found in api logs"

post() {
    curl -s -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" -X "$1" "$base$2" \
        -H "Origin: $base" -H 'Content-Type: application/json' -d "$3"
}

[ "$(post POST /api/setup "{\"setup_token\":\"$token\",\"email\":\"smoke@example.com\",\"display_name\":\"Smoke\",\"password\":\"smoke test password\"}")" = 201 ] \
    || fail "owner setup"
curl -sf -b "$jar" "$base/api/auth/me" | grep -q smoke@example.com || fail "session cookie"
[ "$(post PUT /api/secrets/smoke '{"value":"smoke-secret-value-1234"}')" = 204 ] || fail "save secret"
curl -sf -b "$jar" "$base/api/secrets" | grep -q '1234"' || fail "secret hint"
[ "$(post POST /api/auth/logout '{}')" = 204 ] || fail "logout"

# Containers run as non-root users on read-only filesystems.
[ "$(docker compose exec -T api id -u)" = 10001 ] || fail "api should run as uid 10001"
[ "$(docker compose exec -T web id -u)" != 0 ] || fail "web should not run as root"
if docker compose exec -T api sh -c 'echo x > /app/probe' 2>/dev/null; then
    fail "api filesystem should be read-only"
fi
if docker compose exec -T web sh -c 'echo x > /usr/share/nginx/html/probe' 2>/dev/null; then
    fail "web filesystem should be read-only"
fi
curl -sI "$base/api/health" | grep -qi '^server: uvicorn' && fail "API server header should be hidden"

# Only the web container is published; the API and database are internal.
if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/api/health; then
    fail "API port should not be published"
fi

echo "Compose smoke test passed."
