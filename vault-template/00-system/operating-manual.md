---
type: operating-manual
created: 2026-09-07
---

# Operating Manual

## Purpose

Use one durable local system to capture, choose, advance, review, and complete
meaningful work without depending on conversation memory.

## Kernel v0

Kernel v0 supports:

- one canonical Inbox;
- one area, direction, outcome, project, persistent question, and task loop;
- daily start and closeout;
- one weekly review;
- protected human notes and separate AI workspaces;
- atomic capture writes, hashes, local audit evidence, local Git, and recovery.

Owner-facing commands:

- `edifice start`
- `edifice today`
- `edifice work`
- `edifice work-context`
- `edifice meeting start`
- `edifice meeting series create`
- `edifice meeting series start`
- `edifice project start`
- `edifice project list`
- `edifice project select`
- `edifice project status`
- `edifice project mark`
- `edifice task start`
- `edifice task add`
- `edifice task list`
- `edifice task complete`
- `edifice review-docs start`
- `edifice review-docs add`
- `edifice review-docs gather`
- `edifice review-docs synthesize`
- `edifice review-docs open`
- `edifice review-docs status`
- `edifice context gather`
- `edifice code start`
- `edifice code launch`
- `edifice pdf add`
- `edifice pdf inventory`
- `edifice pdf backup-personal`
- `edifice pdf import-adobe plan`
- `edifice pdf import-adobe apply`
- `edifice migrate inventory`
- `edifice migrate plan`
- `edifice migrate approve`
- `edifice migrate apply`
- `edifice migrate verify`
- `edifice migrate status`
- `edifice review`
- `edifice status`
- `edifice capture`
- `edifice inbox review`
- `edifice inbox process`
- `edifice inbox route`
- `edifice doctor`

## Boundaries

- Personal content and governed local work context use separate directories.
- Work context remains under `20-work` and keeps source, classification, and
  verification metadata.
- Meeting notes are human-owned and remain under the personal or work notes
  boundary selected by the owner.
- Recurring meeting manifests maintain local series identity and history.
  Calendar remains authoritative for recurrence and reminders.
- Work projects and child tasks use stable IDs in local indexes. One registered
  project is selected through `00-system/current.json`.
- Document reviews use persistent manifests, separate manual and AI notes,
  refreshable generated sections, and read-only source access.
- Context refresh replaces only marked generated blocks. Manual context remains
  owner-editable.
- Coding runs record the exact repository revision, work mode, learning level,
  instruction hashes, registered writable paths, and pending evidence gates.
  Starting a run does not launch an agent or verify JIRA. Launching requires a
  separate confirmed command and records the returned Codex task identity.
- Authoritative links and PDF links are preferred. A local PDF copy requires an
  explicit command, source URL, classification, and matching SHA-256.
- Personal and work PDF bytes remain in separate local directories and
  catalogs.
- PDF filenames use lowercase kebab-case derived from content metadata with
  explicit owner overrides for uncertain names.
- Adobe imports use a review manifest, source hashes, explicit personal-scope
  confirmation, resumable apply, and no Adobe mutation.
- Personal PDF additions and Adobe applies reconcile to
  `~/My Drive/Library`; local hashes are verified without claiming remote sync
  completion.
- Legacy source migrations use immutable machine-local packages, review-only
  mappings, explicit verification, and no source or live-note mutation.
- Approved migration batches copy exact bytes into protected destinations with
  hash-bound approval, conflict preflight, rollback, and resumable evidence.
- Secrets, credentials, restricted personal data, and uncontrolled bulk
  exports are prohibited.
- No synchronization.
- No external mutations.
- No scheduled agents or background jobs.
- No source deletion.
- The existing iCloud Obsidian vault remains untouched.

## Authority

- Obsidian Markdown owns durable personal operating state and local work
  projections.
- External systems remain authoritative for their own objects.
- Human notes and final writing remain owner-controlled.
- Agents may maintain reversible operational state within their allowed paths.
- The owner approves consequential decisions, protected edits, external
  effects, publication, and closure.

## Bootstrap and proof

Building the kernel is bootstrap work. Proof begins when the kernel is frozen
and the owner completes the first real deliverable inside it.

Only defects that block or endanger the first delivery interrupt the frozen
kernel. Other improvements go to the Inbox.
