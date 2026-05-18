#!/usr/bin/env bash
# Back up the benchmark corpus tables (bi_reference_docs + bi_pattern_library)
# from Neon to a local plain-SQL file you can restore with psql later.
#
# Usage:
#   ./scripts/backup-corpus.sh
#
# Output:
#   backups/corpus-YYYY-MM-DD.sql
#
# Restore later (into any Postgres):
#   psql "<target-url>" < backups/corpus-YYYY-MM-DD.sql
set -euo pipefail

ENV_FILE=".env"
BACKUP_DIR="backups"
PG_IMAGE="postgres:17-alpine"

log() { printf '[backup-corpus] %s\n' "$*" >&2; }

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

mkdir -p "$BACKUP_DIR"
OUTFILE="$BACKUP_DIR/corpus-$(date -u +%F).sql"
log "writing: $OUTFILE"

docker run --rm "$PG_IMAGE" \
  pg_dump "$NEON_URL" \
    --table=bi_reference_docs \
    --table=bi_pattern_library \
    --no-owner --no-acl \
    --clean --if-exists \
  > "$OUTFILE"

SIZE="$(du -h "$OUTFILE" | cut -f1)"
LINES="$(wc -l < "$OUTFILE")"
log "done. size=$SIZE lines=$LINES"
log "restore with: psql \"<target-url>\" < $OUTFILE"
