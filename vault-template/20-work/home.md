---
type: work-home
created: 2026-09-08
---

# Work Context

## Active context

No work task has been selected.

## Start

Start without external context:

```text
edifice task start \
  --name "Task name" \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

The task becomes the current work item. Add notes and references under its
`Manual context` section.

Capture a human-owned meeting note:

```text
edifice meeting start \
  --title "Meeting title" \
  --scope work \
  --classification netflix-internal
```

Meeting notes open under `20-work/notes/meetings`. Edifice does not read
Calendar, record audio, or modify an external system.

For a recurring 1:1:

```text
edifice meeting series create \
  --title "1:1 with Jordan" \
  --scope work \
  --classification netflix-internal

edifice meeting series start 1-1-with-jordan
```

The standing note preserves recurring preparation context. Each occurrence
links to the prior meeting and appears in the generated series history.

When a task has a JIRA issue and repository, gather its first context note:

```text
edifice context gather \
  --jira KEY \
  --repo /absolute/repository/path \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

Edit the note's `Manual context` sections directly. Later gathers replace only
the marked generated block.

## Review documents

```text
edifice review-docs start \
  --name "Review name" \
  --classification netflix-internal \
  --review-on YYYY-MM-DD

edifice review-docs add REVIEW \
  --link DOCUMENT_URL \
  --title "Document title" \
  --context "Why this document matters to the review"
```

Use `review-docs add`, `gather`, `synthesize`, and `open` for the recurring
workflow. Add accepts raw URLs and pasted Markdown links. Gather enriches the
source list with verified document details.

## References

Store authoritative links and verified projections under `20-work/references`.

## Reports

Store append-only context-gathering and repository-session reports under
`20-work/run-reports`.

## Safety

- Sync must remain disabled.
- External systems remain authoritative.
- No external mutation.
- No secrets or restricted personal data.
