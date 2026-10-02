# Production PR Flow - Multi-Repo Management

**Purpose:** Manage the complete PR workflow for MapleKey Music Academy across all 3 repositories (backend, frontend, docker) from feature branch → develop → production.

**When to use:** After completing a feature and you're ready to take it through develop to production.

---

## What This Skill Does

This skill drives the PR process across 3 separate Git repositories:

1. **Backend:** `maple_key_music_academy_backend/`
2. **Frontend:** `maple-key-music-academy-frontend/`
3. **Docker:** `maple_key_music_academy_docker/`

**The Complete Flow (two branches only — `main` was deleted):**
```
Feature Branch (current)
    ↓ PR #1 (agent opens; owner merges)
develop (daily development)
    ↓ sync: empty merge of origin/production into develop
    ↓ PR #2 develop → production (required checks green; OWNER merges)
production (the owner's merge triggers the GitHub Actions deploy)
```

Nothing is ever pushed to `production`. Branch protection and the "Production" ruleset (MAP-187) require a PR with green required checks and reject direct and force pushes — backend `test` + `pip-audit`; frontend `build_check` + `quality` + `e2e`. Details: `maple_key_music_academy_docker/CLAUDE.md` § Production Gate.

The docker repo has no production deploy of its own: the backend deploy job runs `deployment/*.sh` from docker **`develop`**. Docker `production` is a mirror the owner fast-forwards after a deploy that used new scripts.

---

## Instructions for Claude

You are helping manage PRs across 3 separate repositories. Follow these steps **for each repository** that has changes. Use `git -C <absolute repo path>` for every git command (the shell's cwd resets between calls).

**Production approval gate — HARD STOP (root `.claude/CLAUDE.md`):** never commit to, merge into, or push to `production` without the user explicitly approving the specific changes in the current conversation. Before Step 4, ask: "Ready to push to production. Here's what will be deployed: [list of changes] — [reason]. Approve?" Wait for an explicit yes. Merging the production PR is the owner's action unless the owner explicitly hands it over for that PR.

### Step 1: Identify Which Repos Have Changes

Check each repository for uncommitted or unpushed changes:
- Backend: `/Users/antonilueddeke/Desktop/Projects/MapleKey_music_school/maple_key_music_academy_backend`
- Frontend: `/Users/antonilueddeke/Desktop/Projects/MapleKey_music_school/maple-key-music-academy-frontend`
- Docker: `/Users/antonilueddeke/Desktop/Projects/MapleKey_music_school/maple_key_music_academy_docker`

Run `git -C <repo> status` in each to identify modified files.

### Step 2: Commit Changes (Multiple Focused Commits)

**CRITICAL:** Create multiple small, focused commits rather than one large commit.

**Example commit strategy:**
- Backend: Separate commits for models, serializers, views, tests
- Frontend: Separate commits for types, UI components, queries
- Documentation: Separate commit for CLAUDE.md updates

**Commit message format:**
```
Brief summary (50 chars or less)

Detailed explanation:
- What changed
- Why it changed
- Any side effects

Refs: MAP-XX (ticket number if applicable)
```

**DO NOT include Claude Code signatures** - keep commits clean and professional.

### Step 3: Create PR #1 (Feature → Develop)

For **each repository** with changes:

1. **Ensure the feature branch has the latest develop:**
   ```bash
   git -C <repo> fetch origin
   git -C <repo> checkout <feature-branch>
   git -C <repo> rebase origin/develop   # or: git -C <repo> merge origin/develop
   ```

2. **Push feature branch:**
   ```bash
   git -C <repo> push origin <feature-branch>
   ```

3. **Create PR to develop:**
   ```bash
   gh pr create \
     --repo alueddeke/<repo> \
     --base develop \
     --head <feature-branch> \
     --title "<Feature Name>" \
     --body "$(cat <<'EOF'
## Summary
<Bullet points describing changes>

## Changes by Component
### Backend (if applicable)
- Model changes: ...
- API changes: ...
- Database migrations: ...

### Frontend (if applicable)
- New components: ...
- Type updates: ...
- UI changes: ...

### Docker (if applicable)
- Configuration changes: ...

## Testing
- [ ] Backend tests passing
- [ ] Frontend builds successfully
- [ ] Manual testing completed

## Related
- Refs MAP-XX (if applicable)
EOF
   )"
   ```

4. **Record PR URL** for each repository. The owner merges PR #1. Merged to develop ≠ Done: the Linear ticket stays **In Progress** with a comment "merged to develop <sha>, awaiting prod".

### Step 4: Create PR #2 (Develop → Production)

**ONLY proceed after PR #1 is merged in all repos and the user approved the production changes (gate above).** Backend and frontend only — for docker, see "What This Skill Does".

For each repository:

1. **Sync develop with production.** Production carries its own merge commits and the gate requires the head to be up to date with the base, so merge it into develop first (an empty merge — no file changes):
   ```bash
   git -C <repo> fetch origin
   git -C <repo> checkout develop
   git -C <repo> pull --ff-only origin develop
   git -C <repo> merge --no-edit origin/production
   git -C <repo> push origin develop
   ```

2. **Create the production PR (develop is the head; nothing is pushed to production):**
   ```bash
   gh pr create \
     --repo alueddeke/<repo> \
     --base production \
     --head develop \
     --title "Production: <MAP-xxx short titles>" \
     --body "$(cat <<'EOF'
## Production Deployment

### Changes Included
<Summary of all changes going to production, per ticket>

Closes MAP-xxx
Closes MAP-yyy
Part of MAP-zzz

### Pre-Deployment Checklist
- [ ] Required checks green (backend `test` + `pip-audit`; frontend `build_check` + `quality` + `e2e`)
- [ ] Database migrations reviewed (`11-migration-gate.sh` runs `migrate` + `migrate --check` before any container moves)
- [ ] Environment variables updated (if needed) — 1Password → `scripts/secrets-sync.sh`
- [ ] Monitoring alerts configured

### Post-Deployment Verification
- [ ] `deploy` job green (backup written, migrations verified, `/health/` 200, public 401, image IDs asserted)
- [ ] API rejects anonymous requests: `curl -s -o /dev/null -w '%{http_code}' https://api.maplekeymusic.com/api/auth/user/` → 401
- [ ] Frontend loads: https://maplekeymusic.com
- [ ] Check logs for errors

### Rollback
<revert on develop + the same PR path, or image rollback — maple_key_music_academy_docker/CLAUDE.md § Rollback Procedures>

⚠️ **The owner's merge of this PR triggers the GitHub Actions deployment to DigitalOcean**
EOF
   )"
   ```

   One `Closes MAP-xxx` line per fully shipped ticket — Linear moves those to Done on the production merge. A ticket only partly shipped by this PR gets `Part of MAP-xxx`, which does not close it.

3. **Wait for the required checks**, then hand over: the owner runs `gh pr merge <n> --repo alueddeke/<repo> --merge`. The merge's push to `production` starts the deploy; Actions tags the commit `deploy-YYYY-MM-DD-HHMM`.

---

## Important Notes

1. **Wait for PR approval between steps** - Don't create PR #2 until PR #1 is merged
2. **Handle merge conflicts** - If conflicts arise, resolve them manually on the feature branch or develop, never on production
3. **Run tests** - Ensure tests pass before creating each PR
4. **Check CI/CD** - GitHub Actions runs the required checks on PRs to production; the merge stays blocked until they are green
5. **Monitor deployment** - After the production merge, watch the `deploy` job logs

---

## Example Usage

**Scenario:** You just finished implementing trial lessons (MAP-23)

**Step 1: Invoke skill**
```
/prod-pr
```

**Step 2: Claude will:**
1. Check all 3 repos for changes
2. Create focused commits for backend, frontend, and CLAUDE.md
3. Create PR #1 (feature → develop) for backend and frontend
4. Wait for your merge
5. Ask for production approval with the list of changes
6. After your yes: sync develop with production, create PR #2 (develop → production) with `Closes MAP-23`
7. Wait for the required checks; you merge PR #2

**Step 3: You review and merge each PR**

---

## Troubleshooting

**"Merge conflicts in PR"**
- Resolve locally on the head branch: `git -C <repo> checkout <branch> && git -C <repo> merge <target-branch>`
- Push resolved changes: `git -C <repo> push`

**"Production PR says the branch is out of date"**
- Step 4.1 was skipped: merge `origin/production` into develop and push develop

**"CI/CD failing"**
- Check GitHub Actions logs
- Fix issues locally
- Push fixes to the same branch (PR auto-updates)

**"Need to revert changes"**
- `git -C <repo> revert <commit-hash>` on **develop** (safe, creates new commit), then the same develop → production PR
- Never use `git reset --hard` on shared branches; a force push to production is rejected anyway

---

## Questions to Ask Before Starting

1. What feature/ticket is this for? (for PR titles and `Closes` lines)
2. Are there any breaking changes?
3. Do database migrations need special attention?
4. Should I create draft PRs first for review?
