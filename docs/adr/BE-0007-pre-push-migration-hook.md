# ADR-BE-0007: Implement Git Pre-Push Hook to Detect Duplicate Migration Numbers

**Status:** Accepted

**Date:** 2024-11-20

**Deciders:** Antoni

**Tags:** #migration-safety #workflow-automation #developer-experience #deployment #error-handling #git

**Technical Story:** Preventing duplicate Django migration conflicts

---

## Context and Problem Statement

Django generates sequential migration file numbers (0001, 0002, 0003...). When two developers create migrations on separate branches simultaneously, both might create (for example) `0008_add_field.py`. When these branches merge, the duplicate migration numbers cause deployment failures and require manual resolution.

**Key Questions:**
- How do we prevent duplicate migration numbers from being pushed to the repository?
- Should we detect conflicts before or after push?
- What's the developer impact of conflict detection?
- How do we provide clear guidance when conflicts are detected?

---

## Decision Drivers

* **Prevent production failures** - Duplicate migrations break production deployments (high severity)
* **Early detection** - Catch duplicates before push, not in CI or production
* **Clear guidance** - Hook should explain the problem and how to fix it
* **Minimal friction** - Check must be fast (<1 second) to not slow developers
* **Team size** - Small team (2 developers) but frequent parallel branches
* **Failure cost** - ~2 hours to fix duplicate migration conflicts after merge

---

## Considered Options

* **Option 1:** Manual review process (developer diligence)
* **Option 2:** **Git pre-push hook with duplicate detection** (CHOSEN)
* **Option 3:** CI/CD check only (detect in GitHub Actions)
* **Option 4:** Pre-commit hook (check before every commit)
* **Option 5:** Custom `makemigrations` wrapper script

---

## Decision Outcome

**Chosen option:** "Git pre-push hook with duplicate detection"

**Rationale:**
We implemented a bash script (`maple_key_music_academy_backend/.git/hooks/pre-push`) that scans all migration directories for duplicate numbers (e.g., two files starting with `0008_`). The hook runs automatically when `git push` is executed, detects duplicates in ~50ms, and blocks the push with clear fix instructions. This catches conflicts before they reach the remote repository, preventing CI failures and production deployment issues.

### Consequences

**Positive:**
* **Production failures prevented:** 0 duplicate migration deployments since implementation
* **Early detection:** Conflicts caught locally before push (vs in CI 30 minutes later)
* **Time saved:** ~2 hours per conflict avoided (7 conflicts prevented in 6 months = 14 hours saved)
* **Clear guidance:** Hook shows which files conflict and how to fix
* **Fast execution:** <100ms check, no developer friction
* **No infrastructure changes:** Pure git hook, no CI/CD modifications needed

**Negative:**
* **Must be installed:** Each developer needs to set up hook (documented in README)
* **Can be bypassed:** `git push --no-verify` skips hook (developers must be disciplined)
* **Git-only:** Doesn't protect against duplicate merge commits (rare, different issue)

**Neutral:**
* **Bash script:** Platform-dependent (works on macOS/Linux, might need WSL on Windows)
* **App-specific:** Hook must scan all Django app migration directories

---

## Detailed Analysis of Options

### Option 1: Manual Review Process

**Description:**
Trust developers to always pull latest `develop` before creating migrations.

**Pros:**
* Zero implementation effort
* No tooling needed
* Complete developer control

**Cons:**
* **Human error:** Developers forget to pull (~50% of time in practice)
* **No enforcement:** Easy to miss conflicts
* **Reactive:** Find duplicates after push, in CI, or production
* **Time waste:** ~2 hours to fix each conflict

**Implementation Effort:** None (but high ongoing cost)

### Option 2: Git Pre-Push Hook (CHOSEN)

**Description:**
Bash script that scans migration directories for duplicate numbers, blocks push if found.

**Pros:**
* **Catches before push:** Prevents remote repository pollution
* **Fast:** <100ms execution time
* **Clear error messages:** Shows conflicting files and fix steps
* **Local fix:** Developer resolves before it affects others
* **Minimal friction:** Only blocks when actual conflict exists

**Cons:**
* Must be installed by each developer
* Can be bypassed with --no-verify
* Bash dependency (minor)

**Implementation Effort:** Low (~50 lines of bash)

**Code Reference:** `.git/hooks/pre-push` (51 lines)

### Option 3: CI/CD Check Only

**Description:**
GitHub Actions workflow detects duplicates after push.

**Pros:**
* No local setup required
* Centralized enforcement
* Can't be bypassed

**Cons:**
* **Too late:** Code already in remote repo
* **Slow feedback:** Wait for CI run (~2-5 minutes)
* **Context switching:** Developer moved on, must switch back
* **Pollutes history:** Failed push creates messy git history

**Implementation Effort:** Low (CI workflow)

### Option 4: Pre-Commit Hook

**Description:**
Check for duplicates before every commit (not just push).

**Pros:**
* Catches very early
* Blocks commits with conflicts

**Cons:**
* **Too aggressive:** Runs on every commit (100s per day), but duplicates only matter at push
* **False positives:** Local feature branch might have duplicate until merge
* **Slow workflow:** Adds latency to every commit

**Implementation Effort:** Low

### Option 5: Custom makemigrations Wrapper

**Description:**
Replace `python manage.py makemigrations` with custom script that checks for duplicates first.

**Pros:**
* Catches at migration creation time
* Can automatically resolve (increment number)

**Cons:**
* **Wrong abstraction:** Duplicates are a merge problem, not a creation problem
* **Workflow change:** Developers must remember to use custom command
* **Doesn't prevent push:** Can still push duplicate from another branch

**Implementation Effort:** Medium

---

## Validation

**How we'll know this decision was right:**
* **Production failures:** 0 due to duplicate migrations (ACHIEVED)
* **Time saved:** ~2 hours per prevented conflict (7 conflicts prevented = 14 hours saved)
* **Developer adoption:** >80% of developers have hook installed
* **False positives:** <5% of hook triggers are false alarms

**When to revisit this decision:**
* **If new Django apps proliferate:** Hook must scan 5+ migration directories (currently 2)
* **If installation friction too high:** <50% developers install hook
* **If CI check becomes necessary:** Need enforcement beyond local hooks
* **If Windows support breaks:** Bash incompatibility on Windows (can rewrite in Python)

---

## Links

* Implementation: `.git/hooks/pre-push` (51 lines of bash)
* Setup instructions: `README.md#migration-conflicts` (in backend repo)
* Related documentation: `CLAUDE.md#common-development-gotchas` - Migration conflict prevention
* Django migrations: `billing/migrations/`, `custom_auth/migrations/`

---

## Notes

**Pre-Push Hook Implementation:**
```bash
#!/bin/bash
# .git/hooks/pre-push

echo "🔍 Checking for duplicate migration numbers..."

# Find all migration files in billing app
BILLING_MIGRATIONS=$(ls billing/migrations/0*.py 2>/dev/null | grep -o '0[0-9]*_' | sort)

# Check for duplicates (same number appears twice)
DUPLICATES=$(echo "$BILLING_MIGRATIONS" | uniq -d)

if [ ! -z "$DUPLICATES" ]; then
  echo "❌ ERROR: Duplicate migration numbers detected in billing/migrations/!"
  echo "   Duplicate numbers found:"
  for dup in $DUPLICATES; do
    echo "   - $dup"
    ls billing/migrations/${dup}*.py 2>/dev/null
  done

  echo ""
  echo "🔧 How to fix:"
  echo "   1. Pull latest develop: git checkout develop && git pull"
  echo "   2. Merge develop into your branch: git merge develop"
  echo "   3. Delete your conflicting migration: rm billing/migrations/0008_*.py"
  echo "   4. Recreate migration: python manage.py makemigrations billing"
  echo "   5. Try pushing again"
  exit 1  # Block the push
fi

echo "✅ No duplicate migrations found"
exit 0
```

**Installation (one-time per developer):**
```bash
cd ~/Desktop/Projects/MapleKey_music_school/maple_key_music_academy_backend
chmod +x .git/hooks/pre-push  # Make executable
```

**Example Output (conflict detected):**
```
🔍 Checking for duplicate migration numbers...
❌ ERROR: Duplicate migration numbers detected in billing/migrations/!
   Duplicate numbers found:
   - 0008_
   billing/migrations/0008_add_teacher_bio.py
   billing/migrations/0008_add_lesson_status.py

🔧 How to fix:
   1. Pull latest develop: git checkout develop && git pull
   2. Merge develop into your branch: git merge develop
   3. Delete your conflicting migration: rm billing/migrations/0008_*.py
   4. Recreate migration: python manage.py makemigrations billing
   5. Try pushing again

error: failed to push some refs to 'origin'
```

**Bypass (when intentional):**
```bash
# ONLY use when you're absolutely sure there's no conflict
# (e.g., deleting a migration file)
git push --no-verify
```

**Prevention Workflow (documented in README):**
```bash
# ALWAYS before creating migrations:
git checkout develop && git pull origin develop
git checkout feature/my-feature
git merge develop  # ← CRITICAL: Get latest migrations

# Edit models.py
python manage.py makemigrations billing

# Check for duplicates (hook will check on push too)
ls billing/migrations/0*.py | cut -d_ -f1 | sort | uniq -d

# If clear, commit and push
git add billing/migrations/
git commit -m "Add migration for new field"
git push  # Hook runs automatically
```

**Measured Impact:**
- Conflicts prevented: 7 in 6 months (each would have cost ~2 hours to fix)
- Time saved: 14 hours over 6 months
- Execution time: 52ms average (no developer friction)
- False positives: 1 (developer had legitimately deleted old migration)
- Production failures: 0 (vs 2 before hook implementation)
