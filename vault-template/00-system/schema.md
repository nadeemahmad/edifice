---
type: schema
created: 2026-09-07
---

# Schema

## Managed notes

Managed operational notes contain:

```yaml
id: <type-prefixed-uuid>
type: <registered-type>
schema_version: 1
created: YYYY-MM-DD
status: <type-specific-status>
```

Kernel v0 registers:

- `area`
- `direction`
- `outcome`
- `project`
- `question`
- `review`
- `meeting-note`
- `meeting-series`
- `work-context`
- `work-context-run-report`
- `pdf-catalog`
- `adobe-pdf-import-review`
- `migration-home`
- `document-review`
- `document-review-ai`
- `document-review-run-report`
- `inbox-routing-review`
- `idea-seeds`
- `coding-run`

Tasks remain Markdown checkboxes in the note that owns their context.

## Ownership

- `10-personal/operations`: agent-writeable operational state.
- `10-personal/operations/meeting-series`: recurring personal meeting
  manifests.
- `10-personal/notes`: human-owned and agent-readable.
- `10-personal/notes/meetings`: human-owned personal meeting notes.
- `10-personal/ai`: agent-writeable research and suggestions.
- `20-work/operations`: governed work-task state and approved summaries.
- `20-work/operations/coding-runs`: durable coding-run JSON and local assignment
  previews.
- `20-work/operations/meeting-series`: recurring work meeting manifests.
- `20-work/operations/ideas`: classified work idea seeds that have not been
  promoted into tasks or projects.
- `20-work/references`: links and verified projections from authoritative work
  systems.
- `20-work/notes/meetings`: human-owned work meeting notes.
- `20-work/ai`: enterprise-agent research and synthesis.
- `20-work/run-reports`: append-only work-session reports.
- `10-personal/artifacts/pdfs`: exact local personal PDF copies.
- `10-personal/operations/artifacts`: personal PDF index and Markdown catalog.
- `20-work/references/pdfs`: temporary governed work PDF copies.
- `20-work/references/pdf-catalog.*`: work PDF index and Markdown catalog.
- `20-work/references/document-reviews`: review manifests and validated worker
  results.
- `10-personal/operations/artifacts/imports`: staged Adobe import manifests and
  review notes.
- `10-personal/operations/migrations`: owner-facing migration status and
  resume instructions.
- `10-personal/operations/inbox`: machine-readable capture routing records and
  the owner-facing routing review.
- `01-inbox/inbox.md`: append-only captures and reversible routing.
- `00-system`: protected governance and configuration.
- `90-archive`: read-only except for approved restore or retention work.

## Naming

- Generated vault paths and Markdown filenames use lowercase kebab-case.
- Python uses snake_case.
- Human-facing headings use normal title text.
- Conventional tool files such as `AGENTS.md` retain their required names.

## Work context ownership

- Content between `edifice:generated-context` markers is refreshable.
- Content outside those markers is never replaced by context gathering.
- The `Manual context` sections hold owner notes, links, PDFs, decisions,
  questions, and next actions.
- Local PDF copies record their authoritative source, classification, SHA-256,
  size, and verification result.

## Coding run ownership

- Each run directory contains `coding-run.json` and
  `agent-assignment.preview.json`.
- The run records one active mode, one learning level, the exact repository
  branch and revision, registered writable paths, and hashes for loaded
  repository context.
- JIRA evidence begins as `pending-verification`.
- Assignment launch state is `not-launched`, `launching`, `launched`, or
  `launch-needs-review`. Launch intent records runtime, model, sandbox,
  worktree, and start time before app-server contact. Completed and recovery
  records add the available thread, turn, project, launch time, and instruction
  sources.
- Empty design, TDD, verification, review, closeout, and PR-draft evidence
  lists do not prove that a gate has passed.
- Retrying the same run preserves the original records. Conflicting reuse of a
  run name fails.
- Retrying launch returns the recorded task. Partial or mismatched task
  creation preserves recovery metadata instead of claiming success.

## Meeting note ownership

- Meeting notes use type `meeting-note` and `ownership: human`.
- Standing recurring notes use type `meeting-series` and `ownership: human`.
- Personal notes live under `10-personal/notes/meetings`.
- Work notes live under `20-work/notes/meetings` and require `public`,
  `netflix-internal`, or `netflix-confidential` classification.
- Series manifests are JSON operational records under the matching
  `operations/meeting-series` path.
- Series notes hold owner-written purpose, standing topics, and preparation
  defaults. Edifice may replace only the marked meeting-history block.
- Each occurrence records the stable series identity and links to the closest
  earlier meeting.
- Carry-forward links point to prior notes. Edifice does not copy prior 1:1
  content automatically.
- `created` records the capture date. `meeting_on` records when the meeting
  occurred.
- Agents may read an explicitly relevant meeting note but may not edit it
  without exact owner approval.
- Creation records redacted prepared and committed audit events.
- Meeting capture performs no Calendar lookup, recording, transcription, or
  external mutation.
- Calendar remains authoritative for recurrence, attendance, and reminders.

## Document review ownership

- `20-work/operations/projects/*-document-review.md` contains the manual review
  context and generated synthesis.
- `20-work/ai/*-document-review.md` contains refreshable generated analysis and
  manual analyst notes.
- Only explicit marker blocks may be replaced.
- Session manifests identify every authoritative URL, detected source type,
  owner-attested title and context, and local PDF path.
- Worker results must match the registered document IDs and URLs.
- Gathered source blocks may add verified title, purpose, concise summary, and
  evidence status without replacing owner context.
- External document mutation is not part of the workflow.

## PDF naming

- Canonical PDF filenames use lowercase kebab-case.
- Names derive from confirmed or extracted creator, short title, version, and
  year in the type-specific order.
- The original filename remains in the catalog.
- Topics, projects, workflow status, and reading state stay out of filenames.
- Medium- and low-confidence names require an explicit owner acceptance or
  override.
- A same-name file with different bytes receives a short SHA-256 suffix.
- PDF byte stores are excluded from the vault's local Git history; catalogs,
  manifests, and governance remain versioned.
- Personal catalog entries record `drive_path`, `drive_copy_status`,
  `drive_sync_status`, and `drive_verified_at` after reconciliation.
- `local-hash-verified` proves bytes in the mounted Drive folder. It does not
  prove remote upload completion.

## Adobe import manifest

- `source_completeness` is `trial-required` for local cache discovery and
  `owner-attested` only for an explicitly complete downloaded export.
- Every candidate begins with decision `review`.
- Valid decisions are `review`, `import-personal`, and `skip`.
- Apply rechecks the planned source path and SHA-256 before copying.
- Each successful import records its storage path and timestamp immediately so
  interrupted runs can resume.

## Migration package

Machine-local packages contain:

```text
manifest.json
inventory.json
validation.json
mapping.json
report.md
raw/
proposed/
```

- `raw` preserves exact source bytes and is read-only.
- `inventory.json` records paths, sizes, timestamps, modes, and SHA-256.
- `mapping.json` contains review-only content routing proposals.
- Stable source IDs derive from source path and content hash.
- Supported source kinds are `obsidian`, `craft`, and `coda`.
- Craft Markdown and text become note candidates; TextBundle media remains
  artifact candidates.
- Coda text becomes note candidates; CSV and TSV become table-artifact
  candidates.
- Legacy Netflix-area files may receive reviewed local-only targets under
  `20-work/references/imported` while Sync remains disabled.
- A work-source candidate is excluded from personal-cloud routing, not from
  local Edifice migration.
- Packages remain outside the live vault and normal Git history.
- Encryption remains unavailable until the personal archive key path is
  qualified.

## Migration approval and apply

- Approval selects an exact source-path prefix and route.
- The approval hash covers source identity, proposed content, decision, and
  target while excluding only later apply-status fields.
- `protected-note` routes exact text bytes to
  `10-personal/notes/imported`.
- Apply verifies all raw hashes and target conflicts before writing anything.
- Apply never overwrites different bytes.
- New targets are rolled back if the batch fails.
- Imported content remains unchanged; semantic promotion is separate.
- Mapping and apply records preserve provenance and resumability.
