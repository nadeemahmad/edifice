---
type: work-home
created: 2026-09-08
---

# Work Context

## Active context

No work task has been selected.

## Start

Choose one JIRA issue, repository, document, or other authoritative work object.
Gather its first context note:

```text
edifice context gather \
  --jira KEY \
  --repo /absolute/repository/path \
  --classification netflix-internal \
  --review-on YYYY-MM-DD
```

Edit the note's `Manual context` sections directly. Later gathers replace only
the marked generated block.

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
