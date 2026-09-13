---
id: work-task
status: uncommitted
mode: implementation
---

# Context-Free Work Task

## Objective

Create and select a local work task before JIRA, repository, or document
context is available.

## Current State

- The implementation and tests exist locally.
- The installed launcher exposes the command through the dirty source tree.
- No live task has been created through this command.

## Owned Files

- `src/edifice/work_task.py`
- `tests/test_task_cli.py`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/workflows.md`
- `vault-template/20-work/home.md`

## Dependencies

- `00-system/current.json`
- Governed `20-work/operations/projects`
- Existing `edifice work` navigation

## Verification

- Tests cover creation, current-pointer selection, date validation, duplicate
  protection, navigation, and rollback.
- Re-run focused and full checks after separation.

## Known Gaps

- The generated active project lacks the primary anchor required by the
  accepted project schema.
- Task creation does not yet append prepared and committed audit evidence.
- A task cannot yet be promoted into the coding workflow.

## Write Ownership

One work-task agent may change the owned files. Shared files require the
integration owner.
