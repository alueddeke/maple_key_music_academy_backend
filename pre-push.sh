#!/bin/bash
#
# Pre-push hook to detect duplicate migration numbers
# Prevents pushing code with conflicting Django migrations
#
# To install this hook:
#   cp pre-push.sh .git/hooks/pre-push
#   chmod +x .git/hooks/pre-push
#

echo "🔍 Checking for duplicate migration numbers across all apps..."

# Find all Django app directories with migrations
MIGRATION_DIRS=$(find . -type d -name "migrations" -not -path "*/venv/*" -not -path "*/__pycache__/*" | sort)

if [ -z "$MIGRATION_DIRS" ]; then
  echo "⚠️  Warning: No migrations directories found"
  echo "   Skipping migration check"
  exit 0
fi

FOUND_DUPLICATES=false

# Check each app's migrations directory
for DIR in $MIGRATION_DIRS; do
  APP_NAME=$(echo $DIR | sed 's|^\./||' | sed 's|/migrations||')

  # Skip if no migration files exist
  if ! ls $DIR/*.py 2>/dev/null | grep -v "__init__.py" > /dev/null; then
    continue
  fi

  # Check for duplicate migration numbers in this app
  DUPLICATES=$(ls $DIR/*.py 2>/dev/null | \
    grep -v "__init__.py" | \
    grep -o '0[0-9]*_' | \
    sort | \
    uniq -d)

  if [ ! -z "$DUPLICATES" ]; then
    if [ "$FOUND_DUPLICATES" = false ]; then
      echo ""
      echo "❌ ERROR: Duplicate migration numbers detected!"
      echo ""
      FOUND_DUPLICATES=true
    fi

    echo "   App: $APP_NAME"
    echo "   Duplicate numbers found:"
    for dup in $DUPLICATES; do
      echo "   - $dup"
      # Show which files have this number
      ls $DIR/${dup}*.py 2>/dev/null | sed 's/^/     /'
    done
    echo ""
  fi
done

if [ "$FOUND_DUPLICATES" = true ]; then
  echo "   This will cause migration conflicts for other developers."
  echo ""
  echo "   To fix:"
  echo "   1. Delete your migration: rm <app>/migrations/00XX_your_migration.py"
  echo "   2. Pull latest develop: git pull origin develop"
  echo "   3. Recreate migration: docker compose exec api python manage.py makemigrations"
  echo ""
  echo "   See CLAUDE.md 'Database Migration Best Practices' for more info."
  echo ""
  exit 1
fi

echo "✅ No duplicate migrations found in any app"
exit 0
