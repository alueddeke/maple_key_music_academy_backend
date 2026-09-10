#!/usr/bin/env bash
# MAP-181 lint gate: settings.py may declare a default only for allowlisted
# setting names (scripts/settings-defaults.allow). Everything else is required
# from the environment with no fallback. Runs in the deploy.yml `test` job, so
# build_and_push never sees a settings.py that reintroduces a dev default.
#
# Matching is call-based, not line-based: the whole file is slurped and every
# config(...) / os.getenv(...) / os.environ.get(...) call is examined up to its
# closing parenthesis, so a call split across lines cannot slip past the gate
# (P0 audit 2026-09-09).
set -euo pipefail
cd "$(dirname "$0")/.."

SETTINGS=maple_key_backend/settings.py
ALLOW=scripts/settings-defaults.allow

names=$(perl -0777 -ne '
  while (/(?:config|os\.getenv|os\.environ\.get)\(\s*[\x27"]([A-Za-z_][A-Za-z0-9_]*)[\x27"]([^)]*)\)/g) {
    my ($name, $rest) = ($1, $2);
    print "$name\n" if $rest =~ /default=|,\s*[\x27"]/;
  }' "$SETTINGS" | sort -u)
allowed=$(grep -vE '^[[:space:]]*(#|$)' "$ALLOW" | sort -u)

bad=$(comm -23 <(printf '%s\n' "$names") <(printf '%s\n' "$allowed"))
if [ -n "$bad" ]; then
  echo "check-no-fallbacks: $SETTINGS declares defaults for non-allowlisted settings:"
  printf '  %s\n' $bad
  exit 1
fi
echo "check-no-fallbacks: OK"
