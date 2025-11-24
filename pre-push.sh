#!/bin/bash
#
# Pre-push hook to detect duplicate migration numbers
# Prevents pushing code with conflicting Django migrations
#
# To install this hook:
#   cp pre-push.sh .git/hooks/pre-push
#   chmod +x .git/hooks/pre-push
#

echo "🔍 Checking for duplicate migration numbers..."

# Navigate to migrations directory
if [ ! -d "billing/migrations" ]; then
  echo "⚠️  Warning: billing/migrations directory not found"
  echo "   Skipping migration check"
  exit 0
fi

# Check for duplicate migration numbers
DUPLICATES=$(ls billing/migrations/*.py 2>/dev/null | \
  grep -o '0[0-9]*_' | \
  sort | \
  uniq -d)

if [ ! -z "$DUPLICATES" ]; then
  echo ""
  echo "❌ ERROR: Duplicate migration numbers detected!"
  echo ""
  echo "   Duplicate numbers found:"
  for dup in $DUPLICATES; do
    echo "   - $dup"
    # Show which files have this number
    ls billing/migrations/${dup}*.py 2>/dev/null | sed 's/^/     /'
  done
  echo ""
  echo "   This will cause migration conflicts for other developers."
  echo ""
  echo "   To fix:"
  echo "   1. Delete your migration: rm billing/migrations/00XX_your_migration.py"
  echo "   2. Pull latest develop: git pull origin develop"
  echo "   3. Recreate migration: docker compose exec api python manage.py makemigrations"
  echo ""
  echo "   See CLAUDE.md 'Database Migration Best Practices' for more info."
  echo ""
  exit 1
fi

echo "✅ No duplicate migrations found"
exit 0
