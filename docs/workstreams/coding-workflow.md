---
id: coding-workflow
status: active
mode: implementation
---

# Coding Workflow

## Objective

Provide one owner-facing coding-task workflow that loads the required context
and practices, uses explicit work modes, records evidence, and prepares a
reviewable closeout without unauthorized external mutation.

## Current State

- Decisions D-207 through D-219 define the intended workflow.
- The owner accepted a manual Phase A walking skeleton for one real repository
  and verified JIRA issue.
- The owner accepted the `edifice code start` interface and local coding-run
  storage on 2026-09-13.
- `edifice code start` creates a durable coding-run record and validated active
  assignment preview without launching an agent or contacting JIRA.
- Automatic routing, agent launch, playbook qualification, evidence updates,
  JIRA verification, PR drafting, and external mutation remain unavailable.

## Intended Work Modes

- `research`
- `experiment`
- `design`
- `implementation`
- `verification`
- `review`

## Owned Files

- `docs/workstreams/coding-workflow.md`
- `src/edifice/agent_assignment.py`
- `src/edifice/coding_run.py`
- `src/edifice/coding-run-schema.json`
- `tests/test_agent_assignment.py`
- `tests/test_coding_cli.py`
- `vault-template/20-work/operations/coding-runs/AGENTS.md`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `docs/engineering/owner-practices.md`
- `vault-template/00-system/engineering/owner-practices.md`
- System schema, workflow, and operating guides

## Dependencies

- Completed owner-practices reconciliation.
- Repository-level `AGENTS.md`.
- Workstream registry and context manifest.
- Existing context gatherer.
- One selected real JIRA issue and repository for the pilot.

## Verification

- Define behavior tests before implementation.
- Require exact-revision deterministic verification and independent review.

Implementation evidence:

- Red: the first CLI test failed because `edifice.coding_run` did not exist.
- Green: the command created the run and assignment preview while leaving the
  target repository unchanged.
- Red: an identical retry failed because the run directory already existed.
- Green: an identical retry returned the existing immutable records.
- Red: conflicting retry and interrupted-write failures lacked specific CLI
  errors.
- Green: conflicts preserve the original run, and interrupted writes leave no
  partial directory.
- Red: persistence reason, design evidence, and future verified JIRA fields
  were absent.
- Green: the run schema now reserves those fields without claiming evidence.
- Red: unsafe registered paths were rejected only after context discovery.
- Green: repository-relative path validation now runs before context discovery.

One initial ownership hypothesis was wrong. Moving shared files into feature
ownership broke the existing integration-owner assignment invariant. The
registry now keeps shared files integration-owned and registers only the new
coding-workflow files as feature-owned.

Independent review of revision
`d0a43bf019601c09579d3e27496e5e2a92ec9ce5` found three major issues:

- symlinked writable paths could resolve outside the repository;
- context hashing could race with a worktree change after the clean check;
- read-only modes received write scope while implementation mode prohibited
  repository changes.

Implementation resumed after review. The command now checks resolved-path
containment before context discovery, reads registry and context bytes from the
recorded Git revision, rechecks repository state before publication, and
derives assignment permissions from the selected mode. Focused regression
tests cover each finding.

Independent review of revision
`d13f4bd489d8c281dca77c6ed0c9696be68ab8aa` found a remaining publication
race plus two gaps in the shared assignment validator. Implementation resumed
again:

- repository state is rechecked inside the run lock before and after
  publication, with narrow rollback of an unchanged just-created run;
- assignment validation now rejects resolved paths outside the repository;
- assignment validation now requires empty writable paths for read-only modes;
- a missing committed workstream registry now produces a controlled CLI error.

## Known Gaps

- No skill or playbook has been qualified for the pilot.
- Context hashes prove which instructions the starter read. No agent-load
  acknowledgement exists because this slice does not launch an agent.
- JIRA syntax is validated, but issue title, URL, and status remain unverified.
- Mode transitions and TDD, verification, review, closeout, and PR-draft
  evidence updates remain manual future slices.
- No PR-draft workflow or JIRA verification gate exists.
- The coding-run JSON schema is not executed by a general schema validator.
  Behavior tests check the generated record directly, so schema drift remains
  a minor review risk.

## Write Ownership

The registry records the bounded integration-owner transfer for this slice.
Do not widen the paths or add another coding-workflow capability without an
accepted behavior and test interface.
