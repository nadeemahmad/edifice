---
type: guide
created: 2026-09-07
---

# Getting Started

## Start

```text
edifice start
```

Opens `home.md`, the main cockpit.

## Choose today

```text
edifice today
```

Opens today's daily review. Record one intended result before starting work.

## Resume work

```text
edifice work
```

Opens the project selected in `00-system/current.json`.

## Start work without context

```text
edifice task start \
  --name "Investigate evaluation failures" \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

This creates a local task under `20-work/operations/projects` and selects it
for `edifice work`. No JIRA issue, repository, document, or external access is
required. Add notes, links, PDFs, decisions, and questions under
`Manual context`.

## Capture meeting notes

```text
edifice meeting start \
  --title "Architecture sync" \
  --scope work \
  --classification netflix-internal
```

The command creates and opens a human-owned note under
`20-work/notes/meetings`. Use `--scope personal` for
`10-personal/notes/meetings`, and use `--held-on YYYY-MM-DD` when the meeting
occurred on another date.

The note has sections for attendees, notes, decisions, action items, open
questions, and follow-up. Edifice records redacted audit evidence but does not
read Calendar, record audio, transcribe speech, or change an external system.

For a recurring 1:1, create a reusable series:

```text
edifice meeting series create \
  --title "1:1 with Jordan" \
  --scope work \
  --classification netflix-internal
```

Start each occurrence with:

```text
edifice meeting series start 1-1-with-jordan
```

The occurrence includes preparation prompts and a carry-forward link to the
previous meeting. The standing series note retains owner-written purpose,
topics, and defaults while Edifice refreshes only its marked history block.
Calendar remains authoritative for the recurring event.

## Open work context

```text
edifice work-context
```

Opens the local-only `20-work` cockpit. Work context may remain there only
while Sync is disabled.

## Review documents

Start a reusable review session:

```text
edifice review-docs start \
  --name "Architecture review" \
  --classification netflix-internal \
  --review-on 2026-09-15
```

Add authoritative sources:

```text
edifice review-docs add architecture-review \
  --link DOCUMENT_URL \
  --title "Document title" \
  --context "Why this document matters to the review"
edifice review-docs add architecture-review --pdf-link PDF_URL
```

Raw URLs and pasted Markdown links are accepted. Edifice detects Google Docs,
Sheets, Slides, Forms, Drive files, PDF links, and other web links. The
`--title` and `--context` values remain owner-attested; `gather` adds verified
source title, purpose, summary, and evidence status.

Gather and synthesize:

```text
edifice review-docs gather architecture-review
edifice review-docs synthesize architecture-review
edifice review-docs open architecture-review
```

Write review objectives, criteria, notes, questions, and feedback under
`Manual context`. Generated refreshes never replace those sections.

## Gather work context

```text
edifice context gather \
  --jira KEY \
  --repo /absolute/repository/path \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

The command reads one JIRA issue and one local Git repository through a
read-only Codex worker. It creates or refreshes a note under
`20-work/operations/projects`.

Write directly under `Manual context` whenever you need to add your own notes,
links, PDF references, decisions, questions, or next action. Refresh replaces
only the marked generated block.

To change classification, review date, repository, or persistence reason, edit
the note's frontmatter first and rerun the command with matching values.

Optional inputs:

```text
--link https://authoritative.example/object
--pdf https://authoritative.example/document.pdf
--copy-pdf /absolute/path/document.pdf https://authoritative.example/document.pdf
--accept-pdf-name
```

`--copy-pdf` copies only the file you name. Edifice does not download PDFs and
will not overwrite different existing bytes.
Use `--accept-pdf-name` only after reviewing a medium- or low-confidence
content-derived name.

## Add a PDF

Personal PDF:

```text
edifice pdf add /absolute/path/document.pdf \
  --scope personal \
  --classification personal
```

Work PDF:

```text
edifice pdf add /absolute/path/document.pdf \
  --scope work \
  --classification netflix-internal \
  --source https://authoritative-work-source/document.pdf
```

Edifice reads metadata and bounded first-page text locally through macOS
PDFKit. It proposes a lowercase kebab-case filename, preserves the original
filename and exact bytes, calculates SHA-256, and updates the scope's catalog.

Use `--title`, `--creator`, `--year`, `--version`, or `--kind` to correct
metadata. Use `--accept-name` only after reviewing a medium- or low-confidence
proposal.

Verify all adopted local PDFs:

```text
edifice pdf inventory
```

The inventory checks both scopes for verified hashes, missing files, changed
bytes, and uncataloged PDFs.

Back up every personal PDF to the configured personal Drive library:

```text
edifice pdf backup-personal
```

The installed launcher uses `~/My Drive/Library`. Personal `pdf add` and Adobe
apply commands run this reconciliation automatically. The command never
overwrites different Drive bytes.

## Import from Adobe Cloud

Plan from Acrobat's locally materialized cloud cache:

```text
edifice pdf import-adobe plan
```

This creates JSON and Markdown review files under
`10-personal/operations/artifacts/imports`. It does not copy PDFs.

The local cache is incomplete by definition. To represent all Adobe Cloud PDFs,
first download a complete export through Acrobat, then run:

```text
edifice pdf import-adobe plan \
  --export-dir /absolute/path/adobe-export \
  --export-complete
```

After reviewing the proposed names and confirming the entries belong in the
personal library:

```text
edifice pdf import-adobe apply /absolute/path/manifest.json \
  --confirm-all-personal
```

For a cache-only partial import, also pass `--allow-incomplete-source`.
Edifice verifies every source hash again, imports through the normal PDF
catalog, records progress after each file, and leaves Adobe unchanged.

## Migrate an existing Obsidian vault

Create a complete machine-local snapshot:

```text
edifice migrate inventory \
  --source obsidian \
  --path /absolute/path/to/legacy-vault
```

The command copies no material into the live Edifice vault. It creates an
immutable raw package with hashes, validation, and a cockpit resume point.

Create review-only routing proposals:

```text
edifice migrate plan /absolute/path/to/package
```

Verify package integrity:

```text
edifice migrate verify /absolute/path/to/package
edifice migrate status
```

All mappings remain `review`. Applying selected notes is a later explicit step.

Approve one exact batch:

```text
edifice migrate approve /absolute/path/to/package \
  --source-prefix Essentials/ \
  --route protected-note
```

Apply only approved mappings:

```text
edifice migrate apply /absolute/path/to/package
```

Imported protected notes preserve exact source bytes. The migration package
holds provenance and apply evidence.

Craft and Coda exports use the same commands:

```text
edifice migrate inventory --source craft --path /absolute/craft-export
edifice migrate inventory --source coda --path /absolute/coda-export
```

Craft TextBundle attachments remain linked inside the raw package. Coda text
documents and table exports receive separate review mappings.

## Review the week

```text
edifice review
```

Opens the weekly review containing the current date.

## See current state

```text
edifice status
```

Shows the Inbox count, current project and question, daily and weekly review
paths, and local Git state.

## Capture without interruption

```text
edifice capture "Exact words to preserve"
```

Adds the text to `01-inbox/inbox.md` with a stable ID and redacted audit
evidence.

Process captured notes later:

```text
edifice inbox review
```

The command refreshes and opens
`10-personal/operations/inbox/review.md`. Ambiguous captures stay in the Inbox.
Route one capture after choosing its destination:

```text
edifice inbox route CAPTURE_ID --to current-work-note
```

Use the interactive review for personal and work tasks, notes, questions,
ideas, archive, leave, and quit:

```text
edifice inbox review --interactive
```

The command processes at most five captures by default. It previews the exact
destination and asks for confirmation before every route. Work ideas require a
classification and remain seeds rather than tasks. Archive preserves the raw
capture and records a reversible disposition.

## Check health

```text
edifice doctor
```

Verifies the minimum vault structure and confirms Obsidian Sync is disabled.

## Normal loop

1. Run `edifice today`.
2. Choose one intended result.
3. Run `edifice work`.
4. Use `edifice work-context` when the active task needs work-system context.
5. Run `edifice context gather` for the selected JIRA issue and repository.
6. Use `edifice pdf add` for any PDF that should become a managed local copy.
7. Use `edifice pdf import-adobe plan` for staged Adobe consolidation.
8. Run `edifice pdf backup-personal` to repair or verify Drive backing.
9. Use `edifice migrate status` to resume staged source migrations.
10. Add or edit manual context directly in Obsidian.
11. Capture interruptions without changing focus.
12. Run `edifice inbox review` during triage.
13. Update the project resume point and daily closeout.
14. Run `edifice status`.
15. Use `edifice review` during the weekly review.
