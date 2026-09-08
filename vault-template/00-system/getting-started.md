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

## Open work context

```text
edifice work-context
```

Opens the local-only `20-work` cockpit. Work context may remain there only
while Sync is disabled.

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
```

`--copy-pdf` copies only the file you name. Edifice does not download PDFs and
will not overwrite different existing bytes.

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
6. Add or edit manual context directly in Obsidian.
7. Capture interruptions without changing focus.
8. Update the project resume point and daily closeout.
9. Run `edifice status`.
10. Use `edifice review` during the weekly review.
