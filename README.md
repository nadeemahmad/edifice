# Personal OS

Kernel v0 is a local, personal-only operational system built around Obsidian.

## Boundaries

- The vault is local and unsynchronized.
- Work data is prohibited.
- External mutations and background jobs are disabled.
- Human-owned notes are read-only to agents.
- Captures use atomic writes and append-only audit evidence.

## Commands

```text
personal-os start
personal-os today
personal-os work
personal-os review
personal-os status
personal-os doctor
personal-os capture "Text to preserve"
```

The launcher resolves:

```text
vault: ~/Obsidian/personal-os
audit: ~/Library/Logs/personal-os/personal/audit
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
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pyright
```
