---
id: document-review
status: active
mode: implementation
checkpoint_commit: 2eab90f
integration_commit: 39fa703
---

# Document Review

## Objective

Provide a reusable, read-only workflow for reviewing a bounded set of
authoritative documents while preserving owner context and preventing external
mutation.

## Current State

- Source modules, schema, CLI commands, templates, and tests exist locally.
- One live-vault trial record exists but has not gathered its source.
- The implementation predates the work-task, Inbox, and meeting-note changes.
- Synthesis is bound to the gathered manifest and revalidates document
  identity before publication.
- Synthesis also requires the exact result hash committed by a successful
  gather.
- Review creation rolls back partial files, and PDF metadata is validated
  before ingestion.
- New-source capacity is checked before PDF ingestion.
- Existing PDF links can be upgraded to governed local copies without creating
  duplicate manifest entries.

## Owned Files

- `docs/workstreams/document-review.md`
- `src/edifice/document_review.py`
- `src/edifice/document_review_worker.py`
- `src/edifice/document-review-schema.json`
- `tests/test_document_review_cli.py`
- `vault-template/00-system/templates/document-review.md`
- `vault-template/00-system/templates/document-review-ai.md`
- `vault-template/20-work/references/document-reviews/AGENTS.md`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `src/edifice/context_worker.py`
- `tests/test_doctor_cli.py`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/schema.md`
- `vault-template/00-system/work-context-policy.md`
- `vault-template/00-system/workflows.md`
- `vault-template/20-work/home.md`

## Dependencies

- Existing read-only Codex context-worker invocation.
- Work PDF catalog for explicitly copied local PDFs.
- Governed `20-work` paths and Sync prohibition.

## Verification

- Focused document-review tests exist.
- The latest full source verification passed before repository organization.
- Independent review reproduced stale synthesis, partial creation, metadata
  ordering, and PDF-upgrade failures before their regression fixes.
- Re-run focused and full checks after every further change.

## Known Gaps

- The live review date is stale and no gather has occurred.
- Add and synthesize writes do not yet share one cross-process lock and audit
  contract.

## Write Ownership

One document-review agent may change the owned files. Shared files require the
integration owner.
