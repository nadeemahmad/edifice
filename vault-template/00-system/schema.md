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
- `work-context`
- `work-context-run-report`
- `pdf-catalog`
- `adobe-pdf-import-review`

Tasks remain Markdown checkboxes in the note that owns their context.

## Ownership

- `10-personal/operations`: agent-writeable operational state.
- `10-personal/notes`: human-owned and agent-readable.
- `10-personal/ai`: agent-writeable research and suggestions.
- `20-work/operations`: governed work-task state and approved summaries.
- `20-work/references`: links and verified projections from authoritative work
  systems.
- `20-work/ai`: enterprise-agent research and synthesis.
- `20-work/run-reports`: append-only work-session reports.
- `10-personal/artifacts/pdfs`: exact local personal PDF copies.
- `10-personal/operations/artifacts`: personal PDF index and Markdown catalog.
- `20-work/references/pdfs`: temporary governed work PDF copies.
- `20-work/references/pdf-catalog.*`: work PDF index and Markdown catalog.
- `10-personal/operations/artifacts/imports`: staged Adobe import manifests and
  review notes.
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

## Adobe import manifest

- `source_completeness` is `trial-required` for local cache discovery and
  `owner-attested` only for an explicitly complete downloaded export.
- Every candidate begins with decision `review`.
- Valid decisions are `review`, `import-personal`, and `skip`.
- Apply rechecks the planned source path and SHA-256 before copying.
- Each successful import records its storage path and timestamp immediately so
  interrupted runs can resume.
