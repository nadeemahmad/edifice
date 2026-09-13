---
id: document-library
status: active
mode: implementation
checkpoint_commit: d602db0
integration_commit:
---

# Document Library

## Objective

Maintain a local reading queue for explicitly linked and recently viewed Google
Drive files without copying document content or mutating Google Workspace.

## Accepted Design

- `edifice docs add` resolves one Google Docs or Drive URL and adds its verified
  metadata to the queue, optionally tied to a registered work project.
- `edifice docs sync-recent` imports a bounded set of files ordered by Google's
  `viewedByMeTime`.
- Edifice owns reading state. Google view timestamps are discovery evidence, not
  proof that a document was read.
- A document marked read records the exact Drive version. A later version moves
  it to `changed`, except when the owner archived it.
- The initial work adapter reuses the encrypted per-host OAuth token created by
  `nflx-google`.
- The first slice stores metadata only. Document content, comments, PDF export,
  Markdown export, background sync, and external mutation are out of scope.
- Records store `project_ids`; documents may begin unassigned and be assigned
  or unassigned later.

## Interface

```text
edifice docs add URL --classification CLASSIFICATION --review-on YYYY-MM-DD \
  [--project PROJECT]
edifice docs sync-recent --days DAYS --limit LIMIT \
  --classification CLASSIFICATION --review-on YYYY-MM-DD
edifice docs list [--state STATE]
edifice docs mark DOCUMENT --state STATE
edifice docs categorize DOCUMENT --category CATEGORY
edifice docs assign DOCUMENT (--project PROJECT | --unassign)
edifice docs status
edifice docs open
```

## Storage

```text
20-work/operations/document-library/index.json
20-work/operations/document-library/inbox.md
```

The index records source identity, authoritative URL, metadata timestamps,
classification, persistence reason, review date, reading state, categories,
read version, and verification time.

## Failure Behavior

- Authentication, decryption, Google API, malformed-link, and schema failures
  stop before changing the local index.
- Mutations use one cross-process lock and atomic replacement.
- Audit events contain identifiers and counts, not document titles.
- Synchronization is bounded by explicit day and item limits.

## Owned Files

- `docs/workstreams/document-library.md`
- `pyproject.toml`
- `src/edifice/document_library.py`
- `src/edifice/nflx_google.py`
- `tests/test_document_library_cli.py`
- `uv.lock`

## Temporarily Integration-Owned Files

- `docs/workstreams/registry.json`
- `README.md`
- `src/edifice/cli.py`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/schema.md`
- `vault-template/00-system/work-context-policy.md`
- `vault-template/00-system/workflows.md`
- `vault-template/20-work/home.md`

## Verification

Run focused document-library tests, then all repository-required checks.
