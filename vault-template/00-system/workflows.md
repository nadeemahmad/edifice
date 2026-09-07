---
type: workflows
created: 2026-09-07
---

# Workflows

## Driver

- `personal-os start` opens the home cockpit.
- `personal-os today` opens the current daily review.
- `personal-os work` opens the selected active project.
- `personal-os review` opens the current weekly review.
- `personal-os status` reports the current paths, Inbox count, and Git state.

## Capture

1. Run `personal-os capture "text"`.
2. The command records the exact text in `01-inbox/inbox.md`.
3. The command adds a stable capture ID.
4. The command writes prepared and committed audit events without copying the
   captured text into the audit log.
5. Triage later. Never discard a capture silently.

## Daily start

1. Open `home.md`.
2. Review the current outcome, project, question, and task.
3. Choose one intended result for the day.
4. Record blockers or needed decisions in the daily review.

## Daily closeout

1. Record completed work and evidence.
2. Give unfinished work an explicit next action, waiting condition, or
   deliberate deferral.
3. Update the project resume point.
4. Leave the system ready to resume without conversation history.

## Weekly review

1. Inspect outcome evidence and project movement.
2. Review active and waiting questions.
3. Process unresolved captures.
4. Decide what continues, changes, pauses, or stops.
5. Record workflow friction without redesigning Kernel v0 during the first
   deliverable.
