#!/usr/bin/env bash
# Deploy AI Journalist to Fly.io
# Run once after exporting required secrets or creating a local .env:
#   ./scripts/fly-deploy.sh
# Subsequent deploys: fly deploy --config fly.backend.toml (or frontend)
set -euo pipefail

BACKEND_APP="aijournalist-backend"
FRONTEND_APP="aijournalist-frontend"
REGION="sin"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

required_secrets=(
  ANTHROPIC_API_KEY
  TAVILY_API_KEY
  NEWS_API_KEY
  ALPHA_VANTAGE_API_KEY
  DATABASE_URL
  JWT_SECRET_KEY
  ADMIN_EMAIL
  ADMIN_PASSWORD
)

missing_secrets=()
for secret_name in "${required_secrets[@]}"; do
  if [[ -z "${!secret_name:-}" ]]; then
    missing_secrets+=("$secret_name")
  fi
done

if (( ${#missing_secrets[@]} > 0 )); then
  echo "Missing required environment variables: ${missing_secrets[*]}" >&2
  echo "Set them in your shell or in a local .env file, then rerun this script." >&2
  exit 1
fi

echo "==> Checking flyctl auth..."
flyctl auth whoami

# ── Create apps (safe to re-run — fails silently if already exists) ───────────
echo "==> Creating apps (skip if already exist)..."
flyctl apps create "$BACKEND_APP"  --machines 2>/dev/null || true
flyctl apps create "$FRONTEND_APP" --machines 2>/dev/null || true

# ── Backend secrets ───────────────────────────────────────────────────────────
echo "==> Setting backend secrets..."
flyctl secrets set \
  --app "$BACKEND_APP" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  TAVILY_API_KEY="$TAVILY_API_KEY" \
  NEWS_API_KEY="$NEWS_API_KEY" \
  ALPHA_VANTAGE_API_KEY="$ALPHA_VANTAGE_API_KEY" \
  YOUTUBE_API_KEY="${YOUTUBE_API_KEY:-}" \
  DATABASE_URL="$DATABASE_URL" \
  JWT_SECRET_KEY="$JWT_SECRET_KEY" \
  ADMIN_EMAIL="$ADMIN_EMAIL" \
  ADMIN_PASSWORD="$ADMIN_PASSWORD" \
  AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}" \
  AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}" \
  CORS_ORIGINS="https://${FRONTEND_APP}.fly.dev" \
  TRUSTED_HOSTS="${BACKEND_APP}.fly.dev,${BACKEND_APP}.internal"

# ── Deploy backend ────────────────────────────────────────────────────────────
echo "==> Deploying backend..."
flyctl deploy \
  --config fly.backend.toml \
  --app "$BACKEND_APP" \
  --region "$REGION" \
  --remote-only

# ── Deploy frontend ───────────────────────────────────────────────────────────
echo "==> Deploying frontend..."
flyctl deploy \
  --config fly.frontend.toml \
  --app "$FRONTEND_APP" \
  --region "$REGION" \
  --remote-only

echo ""
echo "==> Done! Open your app:"
flyctl open --app "$FRONTEND_APP"
