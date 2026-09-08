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
5. Capture interruptions without changing focus.
6. Update the project resume point and daily closeout.
7. Run `edifice status`.
8. Use `edifice review` during the weekly review.
