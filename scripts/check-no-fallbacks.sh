#!/usr/bin/env bash
# MAP-181 lint gate: settings.py may declare a default only for allowlisted
# setting names (scripts/settings-defaults.allow). Everything else is required
# from the environment with no fallback. Runs in the deploy.yml `test` job, so
# build_and_push never sees a settings.py that reintroduces a dev default.
set -euo pipefail
cd "$(dirname "$0")/.."

SETTINGS=maple_key_backend/settings.py
ALLOW=scripts/settings-defaults.allow

found=$(grep -nE "(config|os\.getenv|os\.environ\.get)\(.*(default=|, ?')" "$SETTINGS" || true)
names=$(printf '%s\n' "$found" \
  | sed -nE "s/.*(config|os\.getenv|os\.environ\.get)\( *'([A-Za-z_][A-Za-z0-9_]*)'.*/\2/p" \
  | sort -u)
allowed=$(grep -vE '^[[:space:]]*(#|$)' "$ALLOW" | sort -u)

bad=$(comm -23 <(printf '%s\n' "$names") <(printf '%s\n' "$allowed"))
if [ -n "$bad" ]; then
  echo "check-no-fallbacks: $SETTINGS declares defaults for non-allowlisted settings:"
  printf '  %s\n' $bad
  exit 1
fi
echo "check-no-fallbacks: OK"
