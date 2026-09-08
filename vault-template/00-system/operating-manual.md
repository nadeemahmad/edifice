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
- `edifice context gather`
- `edifice pdf add`
- `edifice pdf inventory`
- `edifice pdf import-adobe plan`
- `edifice pdf import-adobe apply`
- `edifice review`
- `edifice status`
- `edifice capture`
- `edifice doctor`

## Boundaries

- Personal content and governed local work context use separate directories.
- Work context remains under `20-work` and keeps source, classification, and
  verification metadata.
- Context refresh replaces only marked generated blocks. Manual context remains
  owner-editable.
- Authoritative links and PDF links are preferred. A local PDF copy requires an
  explicit command, source URL, classification, and matching SHA-256.
- Personal and work PDF bytes remain in separate local directories and
  catalogs.
- PDF filenames use lowercase kebab-case derived from content metadata with
  explicit owner overrides for uncertain names.
- Adobe imports use a review manifest, source hashes, explicit personal-scope
  confirmation, resumable apply, and no Adobe mutation.
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
