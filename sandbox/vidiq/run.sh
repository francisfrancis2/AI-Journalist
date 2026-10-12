#!/usr/bin/env bash
# Runs the probe in its own venv (Python 3.11 + official MCP SDK).
# Isolated from the app: nothing here is on the backend's dependency path.
set -euo pipefail
cd "$(dirname "$0")"
exec ./.venv/bin/python probe.py "$@"
