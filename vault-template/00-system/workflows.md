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
- `edifice meeting start` creates and opens a human-owned meeting note.
- `edifice meeting series create` creates a recurring meeting series.
- `edifice meeting series start` creates its next dated occurrence.
- `edifice task start` creates and selects a task without external context.
- `edifice review-docs` creates and operates reusable document reviews.
- `edifice context gather` creates or refreshes bounded work context.
- `edifice code start` creates a coding-run record and assignment preview.
- `edifice code launch` creates a confirmed persistent Codex task.
- `edifice pdf add` copies and catalogs one intentionally selected PDF.
- `edifice pdf inventory` verifies both local PDF catalogs.
- `edifice pdf backup-personal` reconciles every personal PDF to the configured
  Drive library.
- `edifice pdf import-adobe plan` creates a non-importing Adobe review
  manifest.
- `edifice pdf import-adobe apply` imports approved personal entries.
- `edifice migrate inventory` creates a complete source snapshot and inventory.
- `edifice migrate plan` creates review-only routing proposals.
- `edifice migrate approve` binds a batch rule to the current mapping hash.
- `edifice migrate apply` copies approved mappings into the live vault.
- `edifice migrate verify` validates raw package bytes.
- `edifice migrate status` lists resumable packages.
- `edifice review` opens the current weekly review.
- `edifice status` reports the current paths, Inbox count, and Git state.
- `edifice inbox review` refreshes and opens the routing review.
- `edifice inbox review --interactive` processes a bounded owner-reviewed
  batch.
- `edifice inbox process` identifies captures and refreshes routing review.
- `edifice inbox route` applies one approved reversible route.

## Capture

1. Run `edifice capture "text"`.
2. The command records the exact text in `01-inbox/inbox.md`.
3. The command adds a stable capture ID.
4. The command writes prepared and committed audit events without copying the
   captured text into the audit log.
5. Run `edifice inbox review` during later triage.
6. Review ambiguous captures in
   `10-personal/operations/inbox/review.md`.
7. Use `edifice inbox review --interactive` for a progressive personal, work,
   archive, leave, or quit choice.
8. Classify every work idea explicitly before routing it to the work seed
   note.
9. Preview and confirm the exact local effect.
10. Preserve the Inbox wording and destination link.
11. Re-run processing to detect missing destinations or incomplete routing.
12. Never discard a capture silently.

## Work task

1. Run `edifice task start --name NAME --classification CLASSIFICATION
   --review-on YYYY-MM-DD`.
2. Edifice creates a local project note and selects it as the current work
   item.
3. Define the result and first action in the note.
4. Add manual notes, links, PDFs, decisions, and questions as they become
   available.
5. Gather external context separately when the task acquires an authoritative
   JIRA issue and repository.
6. Run `edifice work` to resume the selected task.

## Meeting notes

1. Run `edifice meeting start --title TITLE --scope SCOPE`.
2. Add `--classification CLASSIFICATION` for every work meeting.
3. Use `--held-on YYYY-MM-DD` when the meeting occurred on another date.
4. Edifice creates and opens a human-owned note in the selected notes boundary.
5. Record attendees, notes, decisions, action items, open questions, and
   follow-up directly in the note.
6. Move durable tasks, project state, or persistent questions into their
   authoritative operational notes after the meeting.
7. Keep Calendar, recordings, transcripts, and shared documents authoritative
   in their existing systems.
8. Do not edit or distribute meeting notes through an external system without
   a separate approved workflow.

For recurring meetings:

1. Run `edifice meeting series create` once with title, scope, and work
   classification when applicable.
2. Record purpose, standing topics, and preparation defaults in the human-owned
   series note.
3. Run `edifice meeting series start SERIES` for each occurrence.
4. Review the carry-forward link and prepare objectives, topics, questions,
   decisions, and pre-reading.
5. Edifice records the occurrence in the local manifest and refreshes only the
   generated history block.
6. Do not treat the series manifest as a Calendar or reminder system.
7. Do not copy sensitive prior content automatically. Follow the previous note
   only when its contents are appropriate for the current meeting.

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

## Coding run

1. Select a real Git repository, registered workstream, objective, JIRA key,
   primary mode, and learning level.
2. Run `edifice code start` from a clean named branch.
3. Inspect the durable coding-run record and active assignment preview.
4. Preview launch with `edifice --dry-run code launch RUN --model MODEL`.
5. Launch only after confirming the project, worktree, model, sandbox, and
   task title.
6. Treat JIRA as unverified until an approved read-only workflow records its
   exact title and URL.
7. Accept a lightweight design before material implementation.
8. Record behavior changes through test-first vertical slices.
9. Verify the exact final revision before independent findings-first review.
10. Prepare a PR description from verified evidence, but do not publish without
   owner approval.
11. Keep mode changes and evidence updates manual until later slices implement
   explicit commands.
12. Do not infer JIRA access, repository mutation, review, or
    publication from the existence of a run record.

## Document review

1. Start one named review with classification and review date.
2. Add raw URLs or pasted Markdown links, with optional owner title and context.
3. Let Edifice detect Google Docs, Drive files, PDFs, and other web sources.
4. Record the objective and review criteria manually.
5. Gather through the read-only allowlisted worker.
6. Inspect the verified source title, purpose, summary, claims, strengths,
   concerns, questions, and proposed feedback.
7. Synthesize agreements, conflicts, gaps, and decision points.
8. Refine the feedback draft manually.
9. Keep external documents authoritative and unchanged.
10. Resume through `review-docs status` rather than conversation history.

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
15. Preflight every approved target before writing the batch.
16. Preserve exact bytes for protected imported notes.
17. Roll back new targets if apply fails.
18. Keep semantic promotion separate from exact-copy migration.

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
