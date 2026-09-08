---
type: workflows
created: 2026-09-07
---

# Workflows

## Driver

- `edifice start` opens the home cockpit.
- `edifice today` opens the current daily review.
- `edifice work` opens the selected active project.
- `edifice work-context` opens the local work cockpit.
- `edifice context gather` creates or refreshes bounded work context.
- `edifice review` opens the current weekly review.
- `edifice status` reports the current paths, Inbox count, and Git state.

## Capture

1. Run `edifice capture "text"`.
2. The command records the exact text in `01-inbox/inbox.md`.
3. The command adds a stable capture ID.
4. The command writes prepared and committed audit events without copying the
   captured text into the audit log.
5. Triage later. Never discard a capture silently.

## Work context

1. Start from one active work task, JIRA issue, repository, or document.
2. Run `edifice context gather --jira KEY --repo /absolute/path
   --classification CLASSIFICATION --review-on YYYY-MM-DD`.
3. Record additional links with `--link` and PDF links with `--pdf`, or add
   them manually in Obsidian.
4. Use `--copy-pdf FILE SOURCE_URL` only for an explicitly approved local copy.
5. Edit notes, decisions, questions, and next actions under `Manual context`.
6. Refresh with the same gather command. Only the generated block changes.
7. Record source, classification, verification time, and persistence decision.
8. Keep raw authoritative content in its work system when a link or summary is
   sufficient.
9. Store no secrets, credentials, restricted personal data, or uncontrolled
   bulk exports.
10. Keep external mutation disabled.
11. Remove or relocate `20-work` before personal Sync is enabled.

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
