---
type: guide
created: 2026-09-07
---

# Getting Started

## Start

```text
personal-os start
```

Opens `home.md`, the main cockpit.

## Choose today

```text
personal-os today
```

Opens today's daily review. Record one intended result before starting work.

## Resume work

```text
personal-os work
```

Opens the project selected in `00-system/current.json`.

## Review the week

```text
personal-os review
```

Opens the weekly review containing the current date.

## See current state

```text
personal-os status
```

Shows the Inbox count, current project and question, daily and weekly review
paths, and local Git state.

## Capture without interruption

```text
personal-os capture "Exact words to preserve"
```

Adds the text to `01-inbox/inbox.md` with a stable ID and redacted audit
evidence.

## Check health

```text
personal-os doctor
```

Verifies the minimum vault structure and confirms Obsidian Sync is disabled.

## Normal loop

1. Run `personal-os today`.
2. Choose one intended result.
3. Run `personal-os work`.
4. Capture interruptions without changing focus.
5. Update the project resume point and daily closeout.
6. Run `personal-os status`.
7. Use `personal-os review` during the weekly review.
