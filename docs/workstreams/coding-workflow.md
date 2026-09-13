---
id: coding-workflow
status: designed
mode: design
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
- No coding command, run schema, playbook registry, or runtime enforcement
  exists.

## Intended Work Modes

- `research`
- `experiment`
- `design`
- `implementation`
- `verification`
- `review`

## Proposed Owned Files

- `docs/workstreams/coding-workflow.md`
- `src/edifice/coding_run.py`
- `src/edifice/coding_worker.py`
- `src/edifice/coding-run-schema.json`
- `tests/test_coding_cli.py`
- `docs/engineering/playbooks/`
- `docs/engineering/skills.json`
- `docs/engineering/skills.schema.json`

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

## Known Gaps

- The run record and command interface remain undecided.
- No skill or playbook has been qualified for the pilot.
- No mechanism proves that an agent loaded every required instruction.
- No PR-draft workflow or JIRA verification gate exists.

## Write Ownership

Keep this workstream in design mode until the owner accepts the coding-run
interface and first implementation slice.
