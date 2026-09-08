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
- `edifice pdf add` copies and catalogs one intentionally selected PDF.
- `edifice pdf inventory` verifies both local PDF catalogs.
- `edifice pdf backup-personal` reconciles every personal PDF to the configured
  Drive library.
- `edifice pdf import-adobe plan` creates a non-importing Adobe review
  manifest.
- `edifice pdf import-adobe apply` imports approved personal entries.
- `edifice migrate inventory` creates a complete source snapshot and inventory.
- `edifice migrate plan` creates review-only routing proposals.
- `edifice migrate verify` validates raw package bytes.
- `edifice migrate status` lists resumable packages.
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

## PDF library

1. Select one PDF intentionally. Do not bulk-import an accessible directory.
2. Choose `personal` or `work` scope and the correct classification.
3. Provide the authoritative source URL for every work PDF.
4. Run `edifice pdf add`.
5. Review a medium- or low-confidence proposed name before using
   `--accept-name`, or provide explicit metadata overrides.
6. Keep the original file unchanged. Edifice copies exact bytes.
7. Use the generated Markdown catalog for browsing and the JSON index for
   deterministic reconciliation.
8. Run `edifice pdf inventory` to detect missing, changed, or uncataloged
   copies.
9. Do not delete the source, upload work content, or move an external file.
10. Reconcile personal PDFs to `~/My Drive/Library`.
11. Treat local Drive hashes as verified and remote sync status as unavailable
    until a separate read-back check succeeds.

## Adobe PDF import

1. Run `edifice pdf import-adobe plan`.
2. Treat cache-only discovery as incomplete.
3. For complete consolidation, download an owner-verified Adobe export and plan
   it with `--export-dir` and `--export-complete`.
4. Review every candidate's proposed name, confidence, source hash, and
   personal-scope decision.
5. Keep ambiguous or non-personal entries as `review` or `skip`.
6. Apply only approved entries.
7. Recheck source hashes immediately before each copy.
8. Record progress after each successful import so a stopped run can resume.
9. Run `edifice pdf inventory`.
10. Keep Adobe files unchanged until a separate retention decision.

## Legacy source migration

1. Inventory one source at a time.
2. Copy exact source bytes into a machine-local raw package.
3. Hash every source and copied file and fail if the source changes during
   inventory.
4. Keep raw files read-only.
5. Verify the package before planning.
6. Propose destinations according to content, not the old folder hierarchy.
7. Keep every mapping in `review`.
8. Import no live note until a separate approved apply step exists.
9. Preserve the full package for migrate-on-touch and later validation.
10. Do not delete or quarantine the source account during this phase.
11. Use TextBundle or Markdown exports for Craft.
12. Use the personal Coda account export, keeping text and table files
    together in one source package.
13. Route legacy work-source candidates only to reviewed local `20-work`
    destinations while Sync remains disabled.
14. Keep personal-cloud eligibility separate from local migration eligibility.

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
