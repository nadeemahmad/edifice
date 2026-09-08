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
```

`--copy-pdf` is explicit. Edifice does not download PDFs. It preserves the
provided bytes without overwriting a different file and records the source,
classification, SHA-256, byte size, and verification result.

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
