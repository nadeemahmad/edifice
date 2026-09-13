---
id: work-task
status: active
mode: implementation
checkpoint_commit: d602db0
integration_commit:
---

# Work Projects And Tasks

## Objective

Maintain multiple durable work projects, select one as current, and attach
stable child tasks to each project before external context is available.

## Current State

- `edifice project start` creates and selects a durable project.
- `edifice project list`, `select`, and `status` operate on the project
  registry.
- `edifice project mark` sets `active`, `on-hold`, or `completed` in both the
  registry and project note.
- `edifice task add`, `list`, and `complete` maintain stable child task records.
- Projects and tasks support separate personal and work scopes.
- Tasks may use the selected project, name a project explicitly, or remain
  unassigned in a scoped inbox.
- Assignment, reassignment, unassignment, and conservative auto-assignment
  preserve stable task identity and assignment history.
- `edifice task start` remains a compatibility alias for project creation.
- Projects and tasks use explicit IDs so later document records can reference
  projects without depending on filenames or the current pointer.

## Owned Files

- `docs/workstreams/work-task.md`
- `src/edifice/work_project.py`
- `src/edifice/work_task.py`
- `tests/test_project_cli.py`
- `tests/test_task_cli.py`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/workflows.md`
- `vault-template/00-system/schema.md`
- `vault-template/00-system/templates/project.md`
- `vault-template/20-work/home.md`

## Dependencies

- `00-system/current.json`
- Governed `20-work/operations/projects`
- Existing `edifice work` navigation

## Verification

- Focused project and task tests: `13 passed`.
- Complete pytest suite: `189 passed`.
- Ruff check: passed.
- Ruff format check: passed.
- Strict Pyright: `0 errors`.
- `git diff --check`: passed.
- Existing `task start` output and rollback coverage remain green.

## Known Gaps

- Document-library records do not yet attach to project IDs.
- A task cannot yet be promoted into the coding workflow.

## Write Ownership

One work-task agent may change the owned files. Shared files require the
integration owner.
