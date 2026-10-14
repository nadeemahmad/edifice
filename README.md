# Edifice

Kernel v0 is a local operational system built around Obsidian.

## Boundaries

- The vault is local and unsynchronized.
- Ordinary active-task work context may live under `20-work`.
- Secrets, credentials, restricted personal data, and uncontrolled bulk
  exports are prohibited.
- External mutations and background jobs are disabled.
- Human-owned notes are read-only to agents.
- Captures use atomic writes and append-only audit evidence.

## Commands

```text
edifice start
edifice today
edifice work
edifice work-context
edifice meeting start --title MEETING --scope work \
  --classification netflix-internal
edifice meeting series create --title SERIES --scope work \
  --classification netflix-internal
edifice meeting series start SERIES
edifice project start --name PROJECT --scope work \
  --classification netflix-internal --review-on YYYY-MM-DD
edifice project list
edifice project select PROJECT
edifice project status PROJECT
edifice project mark PROJECT --status active
edifice task add "TASK" [--project PROJECT | --no-project --scope SCOPE]
edifice task list --project PROJECT
edifice task complete TASK_ID
edifice task assign TASK_ID --project PROJECT
edifice task reassign TASK_ID --project PROJECT
edifice task unassign TASK_ID
edifice task auto-assign TASK_ID [--apply]
edifice review-docs start --name REVIEW \
  --classification netflix-internal --review-on YYYY-MM-DD
edifice review-docs add REVIEW --link DOCUMENT_URL
edifice review-docs gather REVIEW
edifice review-docs synthesize REVIEW
edifice review-docs open REVIEW
edifice review-docs status REVIEW
edifice context gather --jira KEY --repo /absolute/repository/path \
  --classification netflix-internal --review-on YYYY-MM-DD
edifice code start --name RUN --objective OBJECTIVE [--jira KEY] \
  --repo /absolute/repository/path --workstream WORKSTREAM \
  --mode design --learning-level understand \
  --classification netflix-internal --review-on YYYY-MM-DD
edifice code launch RUN --model MODEL
edifice pdf add /absolute/path/document.pdf \
  --scope personal --classification personal
edifice pdf inventory
edifice pdf backup-personal
edifice pdf import-adobe plan
edifice pdf import-adobe apply /absolute/path/manifest.json \
  --allow-incomplete-source --confirm-all-personal
edifice migrate inventory --source obsidian --path /absolute/legacy-vault
edifice migrate inventory --source craft --path /absolute/craft-export
edifice migrate inventory --source coda --path /absolute/coda-export
edifice migrate plan /absolute/migration-package
edifice migrate approve /absolute/migration-package \
  --source-prefix Essentials/ --route protected-note
edifice migrate apply /absolute/migration-package
edifice migrate verify /absolute/migration-package
edifice migrate status
edifice review
edifice status
edifice doctor
edifice capture "Text to preserve"
edifice inbox review
edifice inbox process
edifice inbox route CAPTURE_ID --to current-work-note
```

## Work projects and tasks

### Daily planning

Run `edifice today` throughout the day to open the personal daily review.
The command creates the review if it is missing and adds a link to the matching
`20-work/operations/reviews/daily/YYYY-MM-DD.md` work plan when one exists.
Personal notes remain unchanged, apart from the appended work-plan link.
Work task text stays under `20-work`; it is never copied into the personal
review. Repeated runs do not duplicate the link or create a work plan.

Use `edifice today --date YYYY-MM-DD` for another day. `edifice --dry-run today`
previews creation, linking, and navigation without writing or opening Obsidian.

Start a durable work project before JIRA, repository, or document context is
available:

```text
edifice project start \
  --name "Evaluation reliability" \
  --scope work \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

The command creates and selects
`20-work/operations/projects/evaluation-reliability.md`. It records
the missing external context as `unavailable` or `not-applicable`, leaves
manual sections for notes and references, and makes `edifice work` open the
project. Add stable child tasks with:

```text
edifice task add "Investigate evaluation failures" \
  --project evaluation-reliability
```

Projects and tasks receive stable IDs in local indexes. `edifice task start`
remains a compatibility alias for creating and selecting a project. These
commands never contact an external system.

Personal projects use `--scope personal` and receive the `personal`
classification automatically. A task without `--project` uses the selected
project. Use `--no-project --scope personal|work` for an unassigned task, then
assign, reassign, unassign, or conservatively auto-assign it later.

## Coding runs

Prepare a governed coding run without launching an agent:

```text
edifice code start \
  --name "Implement code start" \
  --objective "Create the first manual coding-run record." \
  --jira EDIFICE-123 \
  --repo /absolute/repository/path \
  --workstream coding-workflow \
  --mode design \
  --learning-level understand \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

The command requires a clean Git repository on a named
`nahmad/<name>-codex` branch. It reads the registered workstream, derives its
writable paths, hashes the required repository instructions and owner
practices, and records the exact revision. It creates:

```text
20-work/operations/coding-runs/<run>/coding-run.json
20-work/operations/coding-runs/<run>/agent-assignment.preview.json
```

JIRA remains authoritative. This first slice validates only the issue-key
syntax and records JIRA verification as pending when `--jira` is supplied.
Runs without a JIRA issue omit the option and record JIRA as `not-applicable`.
Starting a run does not launch an agent, modify the target repository, contact
an external system, or publish a PR.

Preview a Codex task launch without contacting Codex:

```text
edifice --dry-run code launch RUN --model MODEL
```

Launch after reviewing the worktree, model, sandbox, and task title:

```text
edifice code launch RUN --model MODEL
```

The command revalidates the exact assignment and repository, then requires
confirmation. After confirmation, it resolves the saved Codex project from the
repository roots, creates a persistent task from the recorded worktree, names
it, starts the opening turn, and records the returned thread, turn, project,
model, worktree, and loaded instruction sources. Repeating the command returns
the recorded task.

If Codex creates a task that fails project or worktree verification, or creates
a thread but cannot start its opening turn, Edifice records
`launch-needs-review` with the available task identity before returning an
error. Failures known to occur before thread creation record
`launch-retryable` and may be retried after the local cause is corrected.

## Meeting notes

Create and open a human-owned meeting note:

```text
edifice meeting start \
  --title "Architecture sync" \
  --scope work \
  --classification netflix-internal
```

Use `--scope personal` for a personal meeting. Personal notes receive the
`personal` classification automatically. Use `--held-on YYYY-MM-DD` when
capturing notes for a meeting held on another date.

Meeting notes are stored under:

```text
10-personal/notes/meetings
20-work/notes/meetings
```

Each note includes sections for attendees, notes, decisions, action items,
open questions, and follow-up. Creation records redacted prepared and
committed audit events. The command does not read Calendar, invite attendees,
record audio, transcribe speech, or mutate an external system.

For a recurring 1:1, create the series once:

```text
edifice meeting series create \
  --title "1:1 with Jordan" \
  --scope work \
  --classification netflix-internal
```

Create each occurrence from the saved series:

```text
edifice meeting series start 1-1-with-jordan
edifice meeting series start 1-1-with-jordan --held-on 2026-09-16
```

The standing series note holds purpose, standing topics, and preparation
defaults. Each occurrence includes preparation prompts, a carry-forward link
to the prior meeting, and the standard note sections. Edifice refreshes only
the marked meeting-history block in the standing note and preserves all
owner-written content.

Calendar remains authoritative for recurrence and reminders. Series creation
does not schedule a meeting, invite anyone, or copy prior 1:1 content into a
new note.

## Inbox routing

Refresh and open the Inbox review:

```text
edifice inbox review
```

Review up to five captures interactively:

```text
edifice inbox review --interactive
```

The interactive flow asks for personal, work, archive, leave, or quit. Personal
and work choices then ask whether the capture is a task, note, question, or
idea. Every route previews its destination and requires confirmation.

Refresh without opening Obsidian:

```text
edifice inbox process
```

The command adds stable IDs to unchecked lines that were typed directly into
the Inbox. It refreshes:

```text
10-personal/operations/inbox/routing.json
10-personal/operations/inbox/review.md
```

Ambiguous captures remain unchecked. Explicit `work task:`, `work note:`,
`work question:`, and `personal idea:` prefixes receive owner-attested route
suggestions but are not applied silently.

Apply one reviewed route:

```text
edifice inbox route CAPTURE_ID --to current-work-task
edifice inbox route CAPTURE_ID --to current-work-note
edifice inbox route CAPTURE_ID --to current-work-question
edifice inbox route CAPTURE_ID --to personal-project-task
edifice inbox route CAPTURE_ID --to personal-project-note
edifice inbox route CAPTURE_ID --to personal-project-question
edifice inbox route CAPTURE_ID --to personal-idea
edifice inbox route CAPTURE_ID --to work-idea \
  --classification netflix-internal
edifice inbox route CAPTURE_ID --to archive
```

Routing preserves the original Inbox wording, adds a source link and route ID
to the destination, records a redacted audit event, and is safe to retry.
`inbox process` also reports missing or changed destinations.

Personal project routes use the project selected in `00-system/current.json`.
Work routes require a selected project under `20-work/operations/projects`.
Work ideas remain seeds under `20-work/operations/ideas/seeds.md`; they do not
become tasks until promoted.

`context gather` creates or refreshes
`20-work/operations/projects/<jira-key>-context.md`. It replaces only the
explicit generated block. Everything under `Manual context` remains editable
in Obsidian and survives refresh.

Add references while gathering:

```text
--link https://authoritative.example/object
--pdf https://authoritative.example/document.pdf
--copy-pdf /absolute/path/document.pdf https://authoritative.example/document.pdf
--accept-pdf-name
```

`--copy-pdf` is explicit. Edifice does not download PDFs. It preserves the
provided bytes without overwriting a different file and records the source,
classification, SHA-256, byte size, and verification result.
Use `--accept-pdf-name` when the PDF catalog reports a medium- or
low-confidence name.

## Document reviews

Create a reusable work review:

```text
edifice review-docs start \
  --name "Architecture review" \
  --classification netflix-internal \
  --review-on 2026-09-15

edifice review-docs add architecture-review \
  --link DOCUMENT_URL \
  --title "Document title" \
  --context "Why this document matters to the review"
edifice review-docs gather architecture-review
edifice review-docs synthesize architecture-review
edifice review-docs open architecture-review
```

`--link` and `--pdf-link` accept either a raw URL or a pasted Markdown link.
Edifice detects Google Docs, Sheets, Slides, Forms, Drive files, PDF links, and
other web links. Owner-supplied titles and context are recorded as
`owner-attested`.

The workflow stores a persistent manifest, a manual work context note, a
separate AI analysis workspace, the latest validated worker result, and an
append-only run report. Gather replaces only marked generated analysis;
manual context and analyst notes remain unchanged. Gather enriches the
generated document list with the verified title, purpose, concise summary, and
evidence status returned from the authoritative source.

PDF options:

```text
edifice review-docs add REVIEW --pdf-link PDF_URL
edifice review-docs add REVIEW \
  --copy-pdf /absolute/file.pdf SOURCE_URL \
  --title "Document title" \
  --context "Why this PDF matters" \
  --accept-pdf-name
```

The worker runs read-only with only the allowlisted Netflix knowledge search
and content-read tools. External documents are never commented on, edited,
shared, moved, or deleted.

## PDF library

`pdf add` extracts local PDFKit metadata and bounded first-page text, proposes
a lowercase kebab-case filename, copies exact bytes into the local Edifice
library, and updates a JSON-backed Markdown catalog.

The installed launcher configures the personal Drive library as:

```text
~/My Drive/Library
```

Every successful personal `pdf add` and Adobe import apply reconciles the full
personal catalog to that folder. `pdf backup-personal` can be run manually at
any time. Drive copies are hash-verified locally; Google Drive upload status
remains unavailable until a separate Drive read-back path is qualified.

Personal PDFs use:

```text
10-personal/artifacts/pdfs/<broad-kind>/<canonical-name>.pdf
```

Temporary governed work copies use:

```text
20-work/references/pdfs/<broad-kind>/<canonical-name>.pdf
```

Work PDFs require an authoritative source URL. Medium- or low-confidence names
require `--accept-name` or explicit `--title`, `--creator`, `--year`, and
`--version` overrides. `pdf inventory` verifies catalog entries, hashes,
missing files, and uncataloged local copies across both scopes.

### Adobe Cloud import

Create a review manifest from PDFs already materialized in Acrobat's local
cloud cache:

```text
edifice pdf import-adobe plan
```

The cache is not proof of complete Adobe Cloud coverage. For a complete
owner-downloaded Adobe export:

```text
edifice pdf import-adobe plan \
  --export-dir /absolute/path/adobe-export \
  --export-complete
```

Apply only after reviewing the generated manifest:

```text
edifice pdf import-adobe apply /absolute/path/manifest.json \
  --confirm-all-personal
```

Cache-only plans additionally require `--allow-incomplete-source`. Apply
rechecks every SHA-256, imports exact bytes through the personal PDF catalog,
updates progress after each file, and never changes the Adobe source.

## Source migration

The installed launcher stores machine-local migration packages under:

```text
~/Library/Application Support/edifice/migrations
```

Inventory an existing Obsidian vault:

```text
edifice migrate inventory \
  --source obsidian \
  --path /absolute/path/to/legacy-vault
```

Inventory creates a complete read-only raw snapshot, hidden files and
attachments included, with per-file and aggregate SHA-256 evidence. Planning
then creates review-only content routing proposals:

```text
edifice migrate plan /absolute/path/to/package
edifice migrate verify /absolute/path/to/package
```

No legacy source or live Edifice note is changed by inventory, planning, or
verification. The raw package remains local and unencrypted until the personal
migration archive encryption path is available.

Approve and apply one exact batch:

```text
edifice migrate approve PACKAGE \
  --source-prefix Essentials/ \
  --route protected-note

edifice migrate apply PACKAGE
```

Approval is bound to the current mapping hash. Apply verifies the raw package,
preflights every target, refuses different existing bytes, copies exact source
content, rolls back newly created targets on failure, and records resumable
apply evidence.

Craft and Coda exports use the same pipeline:

```text
edifice migrate inventory --source craft --path /absolute/craft-export
edifice migrate inventory --source coda --path /absolute/coda-export
```

Craft Markdown and TextBundle contents become protected-note and attachment
candidates. Coda text documents become note candidates, while CSV and TSV
exports become table-artifact candidates. Every mapping remains `review`.

The launcher resolves:

```text
vault: ~/Obsidian/edifice
audit: ~/Library/Logs/edifice/personal/audit
```

## Development

Create or refresh the project environment:

```text
bin/bootstrap
```

The bootstrap uses a normal wheel installation. Do not replace it with a plain
editable `uv sync` on Python 3.14.

Run verification:

```text
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python .venv/bin/pyright
```
