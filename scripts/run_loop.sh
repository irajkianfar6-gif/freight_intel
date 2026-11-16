#!/usr/bin/env sh
# Hourly loop: collect what is due, rebuild leads, push to monday when a board is set.
set -eu
while true; do
  python -m freight_intel.cli run --config "${CONFIG:-config.yaml}" --due-only --out outputs || true
  if [ -n "${MONDAY_BOARD_ID:-}" ] && [ -n "${MONDAY_API_TOKEN:-}" ]; then
    python -m freight_intel.cli push-monday --board "$MONDAY_BOARD_ID" --leads outputs/leads.json || true
  fi
  sleep "${INTERVAL_SECONDS:-3600}"
done
