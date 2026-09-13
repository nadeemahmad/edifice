---
id: meeting-notes
status: uncommitted
mode: implementation
---

# Meeting Notes

## Objective

Create human-owned personal and work meeting notes, including recurring 1:1
series, without reading Calendar or mutating an external system.

## Current State

- Standalone and recurring meeting commands exist locally.
- Recurring occurrences include preparation prompts, prior-meeting links, and
  generated series history.
- The live vault has not been changed and no real meeting series exists.

## Owned Files

- `src/edifice/meeting_note.py`
- `tests/test_meeting_cli.py`
- `vault-template/20-work/notes/AGENTS.md`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `vault-template/AGENTS.md`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/schema.md`
- `vault-template/00-system/workflows.md`
- `vault-template/10-personal/notes/AGENTS.md`
- `vault-template/20-work/home.md`

## Dependencies

- Human-note ownership rules.
- Work classifications and local-only `20-work` policy.
- Append-only audit storage.

## Verification

- Tests cover personal and work notes, audit redaction, dates, duplicate
  protection, recurring series, previous links, and history preservation.
- Re-run focused and full checks after separation.

## Known Gaps

- Calendar remains the manual recurrence and reminder authority.
- The live vault does not yet contain the new nested work-note rule.
- Meeting actions are not promoted into operational tasks automatically.

## Write Ownership

One meeting-note agent may change the owned files. Shared files require the
integration owner.
