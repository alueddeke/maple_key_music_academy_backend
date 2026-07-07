#!/bin/bash
#
# Pre-push hook to detect duplicate migration numbers
# Prevents pushing code with conflicting Django migrations.
#
# Scans EVERY app's migrations/ directory (billing, custom_auth, and any
# future app), not just billing — see MAP-94.
#
# To install this hook:
#   cp scripts/pre-push.sh .git/hooks/pre-push
#   chmod +x .git/hooks/pre-push
#

echo "🔍 Checking for duplicate migration numbers..."

FOUND_DUPLICATES=0
FOUND_DIRS=0

# Discover every app migrations directory (top-level apps only, skip venvs)
for MIGRATIONS_DIR in */migrations; do
  [ -d "$MIGRATIONS_DIR" ] || continue
  APP=$(dirname "$MIGRATIONS_DIR")

  # Only real Django apps (must contain numbered migrations or __init__.py)
  [ -f "$MIGRATIONS_DIR/__init__.py" ] || continue
  FOUND_DIRS=$((FOUND_DIRS + 1))

  DUPLICATES=$(ls "$MIGRATIONS_DIR"/*.py 2>/dev/null | \
    xargs -n1 basename 2>/dev/null | \
    grep -o '^0[0-9]*_' | \
    sort | \
    uniq -d)

  if [ -n "$DUPLICATES" ]; then
    FOUND_DUPLICATES=1
    echo ""
    echo "❌ ERROR: Duplicate migration numbers detected in $APP!"
    echo ""
    echo "   Duplicate numbers found:"
    for dup in $DUPLICATES; do
      echo "   - $dup"
      # Show which files have this number
      ls "$MIGRATIONS_DIR"/${dup}*.py 2>/dev/null | sed 's/^/     /'
    done
  fi
done

if [ "$FOUND_DIRS" -eq 0 ]; then
  echo "⚠️  Warning: no app migrations directories found"
  echo "   Skipping migration check"
  exit 0
fi

if [ "$FOUND_DUPLICATES" -eq 1 ]; then
  echo ""
  echo "   This will cause migration conflicts for other developers."
  echo ""
  echo "   To fix:"
  echo "   1. Delete your migration: rm <app>/migrations/00XX_your_migration.py"
  echo "   2. Pull latest develop: git pull origin develop"
  echo "   3. Recreate migration: docker compose exec api python manage.py makemigrations"
  echo ""
  echo "   See CLAUDE.md 'Migration Workflow' for more info."
  echo ""
  exit 1
fi

echo "✅ No duplicate migrations found (checked $FOUND_DIRS app(s))"
exit 0
