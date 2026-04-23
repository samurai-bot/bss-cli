# RUNBOOK.md — Phase Execution Workflow

> **The clockwork loop for building BSS-CLI, one phase at a time.** Run this exact sequence for every phase. It trades a few minutes of ceremony per phase for a clean history, reversible experiments, and the ability to diff any two phases against each other.

## Prerequisites (one-time, already done)

- [x] Repo cloned / initialized on build machine (agentic-vm)
- [x] `git` identity configured (`user.name`, `user.email`)
- [x] `gh auth status` shows logged in
- [x] `phase-0` tag exists on `main`
- [x] Claude Code installed and authenticated
- [x] Docker + docker compose working (rootless)
- [x] `uv` installed

## The phase loop (repeat for every phase)

Every phase follows the same 9 steps. Call them **P1 through P9**. Learn them once, run them on autopilot.

---

### P1 — Start fresh on main

```bash
cd ~/claude/bss-cli
git checkout main
git pull origin main
git status                # must show: "working tree clean"
```

If `git status` shows anything dirty, stop and figure out why before continuing. Never start a phase on top of uncommitted work.

---

### P2 — Create the phase branch

```bash
# Replace NN with the phase number (01, 02, ..., 10)
export PHASE=phase-02
git checkout -b ${PHASE}
```

Naming convention: `phase-NN` zero-padded, so branches sort correctly.

---

### P3 — Read the phase spec yourself first

Before Claude Code touches anything, read the phase spec and make sure you agree with it.

```bash
less phases/PHASE_02.md
```

Look for: Goal, Deliverables, Out of scope, Verification checklist. The checklist is what you'll run at the end — read it now so you know what "done" looks like.

If the spec needs amendment, do it BEFORE starting the phase:

```bash
git checkout main
# edit phases/PHASE_NN.md
git add phases/PHASE_NN.md
git commit -m "docs(phase-NN): amend spec — <reason>"
git push origin main
git checkout ${PHASE}
git rebase main
```

Never amend the spec mid-phase. That's how scope creeps.

---

### P4 — Open a fresh Claude Code session

```bash
cd ~/claude/bss-cli
claude
```

**Always a fresh session per phase.** Do not continue a previous phase's session into the next phase.

---

### P5 — Run the session prompt

Each phase spec has a "Session prompt" section at the bottom. Copy it verbatim as your first message to Claude Code.

**Critical rule: the spec always says "Do not commit."** Claude Code must not make git commits. You make commits after manual verification.

---

### P6 — Let Claude Code execute the plan

Claude Code will:
1. Read the doctrine files
2. Produce a plan (pauses for your approval)
3. You review, push back if needed, approve when right
4. Implements in sub-steps, pausing at checkpoints
5. Runs the verification checklist and pastes results

Your job: read the plan carefully before approving. Intervene if it goes sideways (scope creep, skipped tests, policy layer bypass). Do not micromanage internal structure when it's not in the spec.

---

### P7 — Manual verification

**This is the gate.** Never skip it. Run the verification checklist from the phase spec yourself, end-to-end, on your own terminal.

```bash
make build
make up-all       # or `make up` for BYOI
sleep 10
make migrate      # phases 2+
make seed         # phases 2+
make test
# plus phase-specific curl / psql checks
```

For each checkbox in the phase's Verification checklist section:
- Run the check
- Confirm the expected result
- If any check fails → back to Claude Code, fix, re-verify

**Do not proceed past this step with any checkbox red.** A half-verified phase poisons every phase that follows.

---

### P8 — Commit and tag

Only after P7 is fully green.

```bash
git status
git diff --stat

git add .
git commit -m "feat(phase-NN): <one-line summary>

<2-5 bullets describing what was added>

- Service X implemented with <key pattern>
- Y tests added, all passing
- Verification checklist: all green"

git tag -a phase-NN -m "Phase NN complete: <summary>"
```

Commit message conventions:
- `feat(phase-NN):` — implementation phases
- `chore(phase-NN):` — infra/scaffolding
- `docs(phase-NN):` — spec amendments

One commit per phase. Squash with `git rebase -i` if you made multiple during debugging.

---

### P9 — Merge to main and push

```bash
# Back to main
git checkout main
git pull origin main

# Fast-forward merge (no merge commit)
git merge --ff-only ${PHASE}

# Push main
git push origin main

# Push the tag — use refs/tags/ to avoid ambiguity with branch name
git push origin refs/tags/${PHASE}

# Delete local phase branch
git branch -d ${PHASE}

# Clear env var for next phase
unset PHASE
```

**Why `refs/tags/` on the tag push:** if you write `git push origin phase-NN`, git sees both a branch and a tag with that name (the branch still exists at push time — it's deleted on the next line) and refuses with `src refspec phase-NN matches more than one`. The explicit `refs/tags/` form disambiguates.

**Why `--ff-only`:** keeps `main` linear, no merge commits. Every phase tag sits directly on `main`.

**Why no remote feature branch:** the phase branch is a local workspace. Solo work → local only is cleaner.

---

## Phase complete checklist

- [ ] Verification checklist all green (P7)
- [ ] Committed with conventional commit message (P8)
- [ ] Tagged `phase-NN` (P8)
- [ ] Merged fast-forward to `main` (P9)
- [ ] Pushed `main` and tag to origin (P9)
- [ ] Local phase branch deleted (P9)
- [ ] Env var unset (P9)
- [ ] `git log --oneline` shows clean linear history
- [ ] `git tag` shows the new tag
- [ ] `git ls-remote --tags origin` confirms tag on GitHub

---

## Diffing phases

```bash
# What did phase 3 add?
git diff phase-02 phase-03

# Scoped to a path
git diff phase-02 phase-03 -- services/catalog/

# Size only
git diff phase-02 phase-05 --stat

# Commit messages across phases
git log --oneline phase-0..phase-10
```

---

## Emergency procedures

### Phase N is broken after merge

```bash
git checkout main
git reset --hard phase-$((N-1))
git push --force-with-lease origin main
git tag -d phase-NN
git push origin :refs/tags/phase-NN
git checkout -b phase-NN
# redo the phase
```

Warning: `--force-with-lease` rewrites history. Solo work only.

### Claude Code made a mess mid-phase

```bash
git checkout .           # discard modifications
git clean -fd            # delete untracked files
# reopen Claude Code, try again
```

### Committed on the wrong branch

```bash
# Save the commit as a phase branch
git branch phase-NN

# Reset main
git reset --hard phase-$((N-1))

# Continue on phase branch
git checkout phase-NN
```

### Spec has a factual error blocking progress

Only exception to "never amend mid-phase":

```bash
git stash
git checkout main
# edit phases/PHASE_NN.md
git add phases/PHASE_NN.md
git commit -m "docs(phase-NN): fix <specific error>"
git push origin main
git checkout phase-NN
git rebase main
git stash pop
```

---

## Quick reference — the whole loop

```bash
# P1: start clean
cd ~/claude/bss-cli && git checkout main && git pull origin main && git status

# P2: branch
export PHASE=phase-NN
git checkout -b ${PHASE}

# P3: read spec
less phases/PHASE_${PHASE#phase-}.md

# P4: fresh Claude Code session
claude

# P5: paste session prompt from the spec

# P6: approve plan, let it run

# P7: verify manually
make build && make up-all && sleep 10 && make migrate && make seed && make test
# plus phase-specific checks

# P8: commit + tag
git add .
git commit -m "feat(${PHASE}): <summary>

- ...
- Verification checklist: all green"
git tag -a ${PHASE} -m "${PHASE} complete"

# P9: merge + push
git checkout main
git pull origin main
git merge --ff-only ${PHASE}
git push origin main
git push origin refs/tags/${PHASE}
git branch -d ${PHASE}
unset PHASE
```

---

## The discipline (why this loop matters)

**Phase isolation makes regression cheap.** If phase 7 breaks something from phase 4, `git diff phase-06 phase-07` tells you exactly what changed. Without tags, you're archaeology-digging.

**Fresh Claude Code sessions per phase prevent drift.** Long sessions build up implicit state that's invisible to future sessions and future you. One phase = one session = one commit = one tag = one coherent chunk.

**Manual verification is the gate.** Claude Code will tell you a phase is done when the happy path works but edge cases are broken. Run the checklist yourself, on your own terminal, with your own eyes. Every time.

**Commit messages are for future-you.** In 3 months when you're debugging Phase 11, `feat(phase-07): COM + SOM + provisioning sim with eSIM` is useful. `stuff` is not.

**`main` is always shippable.** Every tag should be a state where `make up-all && make test` works. Broken tag = emergency rewind, not "fix it next phase".
