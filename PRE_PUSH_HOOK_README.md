# Pre-Push Hook for Migration Conflict Detection

## What It Does

This pre-push hook automatically checks for duplicate Django migration numbers before you push code. It prevents migration conflicts that can break deployment for other developers.

## Installation

**For new developers:**
```bash
cd maple_key_music_academy_backend
cp pre-push.sh .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

**To verify it's installed:**
```bash
.git/hooks/pre-push
# Should output: ✅ No duplicate migrations found
```

## How It Works

When you run `git push`, the hook automatically:
1. Scans `billing/migrations/` for migration files
2. Checks for duplicate migration numbers (e.g., two files starting with `0008_`)
3. If duplicates found: **Blocks the push** and shows which files conflict
4. If no duplicates: Allows push to proceed

## Example Output

**✅ Success (no duplicates):**
```
🔍 Checking for duplicate migration numbers...
✅ No duplicate migrations found
```

**❌ Blocked (duplicates found):**
```
🔍 Checking for duplicate migration numbers...

❌ ERROR: Duplicate migration numbers detected!

   Duplicate numbers found:
   - 0008_
     billing/migrations/0008_add_field_x.py
     billing/migrations/0008_add_field_y.py

   This will cause migration conflicts for other developers.

   To fix:
   1. Delete your migration: rm billing/migrations/00XX_your_migration.py
   2. Pull latest develop: git pull origin develop
   3. Recreate migration: docker compose exec api python manage.py makemigrations

   See CLAUDE.md 'Database Migration Best Practices' for more info.
```

## Troubleshooting

**Hook not running:**
- Check it's executable: `chmod +x .git/hooks/pre-push`
- Check it exists: `ls -la .git/hooks/pre-push`
- Reinstall: `cp pre-push.sh .git/hooks/pre-push`

**Need to bypass hook (emergency only):**
```bash
git push --no-verify
```
⚠️ **WARNING:** Only use `--no-verify` if you're absolutely certain there are no conflicts!

## Why This Matters

Migration conflicts are the #1 cause of deployment issues. This hook:
- Prevents pushing conflicting migrations
- Saves hours of debugging time
- Protects other developers from database issues
- Enforces best practices automatically

## Related Documentation

- [CLAUDE.md - Database Migration Best Practices](../CLAUDE.md#database-migration-best-practices-required-reading)
- [DEVELOPER_WORKFLOW.md - Migration Conflict Prevention](../DEVELOPER_WORKFLOW.md#-migration-conflict-prevention-checklist)
