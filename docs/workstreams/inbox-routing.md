---
id: inbox-routing
status: active
mode: implementation
checkpoint_commit: bacd857
integration_commit: 39fa703
---

# Inbox Routing

## Objective

Identify, review, route, archive, and reconcile canonical Inbox captures
without losing their original wording.

## Current State

- Deterministic processing, interactive review, routing, archive, and tests
  exist locally.
- The live Inbox has two archived test captures and no unresolved captures.
- No semantic AI worker participates in routing.
- Classification is accepted only for work ideas and cannot cross into a
  personal destination.
- Completed captures permit only an idempotent retry of the same route.
- Interrupted captures must retry the recorded route and classification before
  another disposition can be selected.

## Owned Files

- `docs/workstreams/inbox-routing.md`
- `src/edifice/inbox.py`
- `tests/test_inbox_cli.py`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/schema.md`
- `vault-template/00-system/workflows.md`

## Dependencies

- Canonical `01-inbox/inbox.md`
- `00-system/current.json`
- Existing personal and work project-note section contracts
- Append-only audit storage

## Verification

- Tests cover identification, suggestions, personal and work routing,
  idempotency, archive, reconciliation, and interactive review.
- Re-run focused and full checks after separation.

## Known Gaps

- No first-class unarchive or timed defer command exists.
- Personal and work routes share one polymorphic current-work pointer.
- Interactive review cannot select another named project.
- Inbox processing writes routing state without its own audit event.

## Write Ownership

One Inbox-routing agent may change the owned files. Shared files require the
integration owner.
