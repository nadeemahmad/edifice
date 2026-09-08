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
edifice context gather --jira KEY --repo /absolute/repository/path \
  --classification netflix-internal --review-on YYYY-MM-DD
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
edifice migrate verify /absolute/migration-package
edifice migrate status
edifice review
edifice status
edifice doctor
edifice capture "Text to preserve"
```

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
