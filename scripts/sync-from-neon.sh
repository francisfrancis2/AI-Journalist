#!/usr/bin/env bash
# Sync the local Docker Postgres with the Neon production database.
# Usage:
#   ./scripts/sync-from-neon.sh           # snapshot replace
#   ./scripts/sync-from-neon.sh --reset   # wipe local volume first (use if schemas have drifted)
set -euo pipefail

ENV_FILE=".env"
LOCAL_CONTAINER="aijournalist-db"
LOCAL_USER="aijournalist"
LOCAL_DB="aijournalist"
LOCAL_PASSWORD="secret"
PG_IMAGE="postgres:17-alpine"

log() { printf '[sync-from-neon] %s\n' "$*" >&2; }

if [[ ! -f "$ENV_FILE" ]]; then
  log "ERROR: $ENV_FILE not found. Run from repo root."
  exit 1
fi

NEON_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [[ -z "$NEON_URL" ]]; then
  log "ERROR: DATABASE_URL not set in $ENV_FILE"
  exit 1
fi

NEON_HOST="$(printf '%s' "$NEON_URL" | sed -E 's|^[^@]+@([^/?]+).*|\1|')"
log "source: $NEON_HOST"
log "target: docker container $LOCAL_CONTAINER ($LOCAL_DB)"

if [[ "${1:-}" == "--reset" ]]; then
  log "wiping local DB volume (--reset)"
  docker compose down -v db >/dev/null 2>&1 || true
fi

# Ensure local db is up and healthy before restoring into it.
if ! docker ps --format '{{.Names}}' | grep -q "^${LOCAL_CONTAINER}$"; then
  log "starting local db container"
  docker compose up -d db >/dev/null
fi

log "waiting for local db to accept connections"
for i in {1..30}; do
  if docker exec "$LOCAL_CONTAINER" pg_isready -U "$LOCAL_USER" -d "$LOCAL_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Kick existing sessions so DROP statements in the dump don't deadlock.
docker exec -e PGPASSWORD="$LOCAL_PASSWORD" "$LOCAL_CONTAINER" \
  psql -U "$LOCAL_USER" -d postgres -v ON_ERROR_STOP=1 -c "
    SELECT pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = '$LOCAL_DB' AND pid <> pg_backend_pid();
  " >/dev/null

log "dumping from Neon and restoring into local — this may take a few minutes"
docker run --rm "$PG_IMAGE" \
  pg_dump "$NEON_URL" \
    --no-owner --no-acl --clean --if-exists \
  | docker exec -i -e PGPASSWORD="$LOCAL_PASSWORD" "$LOCAL_CONTAINER" \
      psql -U "$LOCAL_USER" -d "$LOCAL_DB" -v ON_ERROR_STOP=1 \
  >/dev/null

log "done. local DB now mirrors Neon as of $(date -u +%FT%TZ)"
