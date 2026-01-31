# Production PR Flow - Multi-Repo Management

**Purpose:** Manage the complete PR workflow for MapleKey Music Academy across all 3 repositories (backend, frontend, docker) from feature branch → develop → main → production.

**When to use:** After completing a feature and you're ready to merge through all branches to production.

---

## What This Skill Does

This skill automates the PR creation process across 3 separate Git repositories:

1. **Backend:** `maple_key_music_academy_backend/`
2. **Frontend:** `maple-key-music-academy-frontend/`
3. **Docker:** `maple_key_music_academy_docker/`

**The Complete Flow:**
```
Feature Branch (current)
    ↓ PR #1
develop (daily development)
    ↓ PR #2
main (code review gate)
    ↓ PR #3
production (deployment - triggers GitHub Actions)
```

---

## Instructions for Claude

You are helping manage PRs across 3 separate repositories. Follow these steps **for each repository** that has changes:

### Step 1: Identify Which Repos Have Changes

Check each repository for uncommitted or unpushed changes:
- Backend: `/Users/antonilueddeke/Desktop/Projects/MapleKey_music_school/maple_key_music_academy_backend`
- Frontend: `/Users/antonilueddeke/Desktop/Projects/MapleKey_music_school/maple-key-music-academy-frontend`
- Docker: `/Users/antonilueddeke/Desktop/Projects/MapleKey_music_school/maple_key_music_academy_docker`

Run `git status` in each to identify modified files.

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

1. **Ensure develop is up to date:**
   ```bash
   git checkout develop
   git pull origin develop
   git checkout <feature-branch>
   git merge develop  # Merge latest develop into feature
   ```

2. **Push feature branch:**
   ```bash
   git push origin <feature-branch>
   ```

3. **Create PR to develop:**
   ```bash
   gh pr create \
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
- Closes MAP-XX (if applicable)

🤖 Generated via Claude Code prod-pr skill
EOF
   )"
   ```

4. **Record PR URL** for each repository

### Step 4: Create PR #2 (Develop → Main)

**ONLY proceed after PR #1 is merged in all repos**

For each repository:

1. **Update develop:**
   ```bash
   git checkout develop
   git pull origin develop
   ```

2. **Ensure main is up to date:**
   ```bash
   git checkout main
   git pull origin main
   git merge develop  # Merge develop into main locally
   ```

3. **Push and create PR:**
   ```bash
   git push origin main
   gh pr create \
     --base main \
     --head develop \
     --title "Merge develop to main - <Sprint/Release Name>" \
     --body "Promoting develop changes to main for code review before production deployment"
   ```

### Step 5: Create PR #3 (Main → Production)

**ONLY proceed after PR #2 is merged in all repos**

For each repository:

1. **Update main:**
   ```bash
   git checkout main
   git pull origin main
   ```

2. **Ensure production is up to date:**
   ```bash
   git checkout production
   git pull origin production
   git merge main  # Merge main into production locally
   ```

3. **Push and create PR:**
   ```bash
   git push origin production
   gh pr create \
     --base production \
     --head main \
     --title "Deploy to Production - <Release Name>" \
     --body "$(cat <<'EOF'
## Production Deployment

### Changes Included
<Summary of all changes going to production>

### Pre-Deployment Checklist
- [ ] All tests passing
- [ ] Database migrations reviewed
- [ ] Environment variables updated (if needed)
- [ ] Monitoring alerts configured

### Post-Deployment Verification
- [ ] API health check: https://api.maplekeymusic.com/health
- [ ] Frontend loads: https://maplekeymusic.com
- [ ] Check logs for errors

⚠️ **This will trigger GitHub Actions deployment to Digital Ocean**

🤖 Generated via Claude Code prod-pr skill
EOF
   )"
   ```

---

## Important Notes

1. **Wait for PR approval between steps** - Don't create PR #2 until PR #1 is merged
2. **Handle merge conflicts** - If conflicts arise, resolve them manually
3. **Run tests** - Ensure tests pass before creating each PR
4. **Check CI/CD** - GitHub Actions will run on PRs to production
5. **Monitor deployment** - After production merge, watch the deployment logs

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
4. Wait for your approval to continue
5. After merge, create PR #2 (develop → main)
6. After merge, create PR #3 (main → production)

**Step 3: You review and merge each PR**

---

## Troubleshooting

**"Merge conflicts in PR"**
- Resolve locally: `git checkout <branch> && git merge <target-branch>`
- Push resolved changes: `git push`

**"CI/CD failing"**
- Check GitHub Actions logs
- Fix issues locally
- Push fixes to the same branch (PR auto-updates)

**"Need to revert changes"**
- Use `git revert <commit-hash>` (safe, creates new commit)
- Never use `git reset --hard` on shared branches

---

## Questions to Ask Before Starting

1. What feature/ticket is this for? (for PR titles)
2. Are there any breaking changes?
3. Do database migrations need special attention?
4. Should I create draft PRs first for review?
