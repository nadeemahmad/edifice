---
id: coding-workflow
status: active
mode: implementation
---

# Coding Workflow

## Objective

Provide one owner-facing coding-task workflow that loads the required context
and practices, uses explicit work modes, records evidence, and prepares a
reviewable closeout without unauthorized external mutation.

## Current State

- Decisions D-207 through D-219 define the intended workflow.
- The owner accepted a manual Phase A walking skeleton for one real repository
  and verified JIRA issue.
- The owner accepted the `edifice code start` interface and local coding-run
  storage on 2026-09-13.
- `edifice code start` creates a durable coding-run record and validated active
  assignment preview without launching an agent or contacting JIRA.
- `edifice code launch` previews and confirms one persistent Codex task through
  the local app-server daemon, then records its task identity.
- Automatic routing, playbook qualification, checkpoint capture, JIRA
  verification, PR drafting, and unrelated external mutation remain
  unavailable.

## Intended Work Modes

- `research`
- `experiment`
- `design`
- `implementation`
- `verification`
- `review`

## Owned Files

- `docs/agent-context.md`
- `docs/engineering/agent-assignment.example.json`
- `docs/workstreams/coding-workflow.md`
- `src/edifice/agent_assignment.py`
- `src/edifice/coding_launch.py`
- `src/edifice/coding_run.py`
- `src/edifice/coding-run-schema.json`
- `tests/test_agent_assignment.py`
- `tests/test_coding_launch_cli.py`
- `tests/test_coding_cli.py`
- `vault-template/20-work/operations/coding-runs/AGENTS.md`

## Shared Files

- `README.md`
- `src/edifice/cli.py`
- `docs/engineering/owner-practices.md`
- `vault-template/00-system/engineering/owner-practices.md`
- System schema, workflow, and operating guides

## Dependencies

- Completed owner-practices reconciliation.
- Repository-level `AGENTS.md`.
- Workstream registry and context manifest.
- Existing context gatherer.
- One selected real JIRA issue and repository for the pilot.

## Verification

- Define behavior tests before implementation.
- Require exact-revision deterministic verification and independent review.

Implementation evidence:

- Red: the first CLI test failed because `edifice.coding_run` did not exist.
- Green: the command created the run and assignment preview while leaving the
  target repository unchanged.
- Red: an identical retry failed because the run directory already existed.
- Green: an identical retry returned the existing immutable records.
- Red: conflicting retry and interrupted-write failures lacked specific CLI
  errors.
- Green: conflicts preserve the original run, and interrupted writes leave no
  partial directory.
- Red: persistence reason, design evidence, and future verified JIRA fields
  were absent.
- Green: the run schema now reserves those fields without claiming evidence.
- Red: unsafe registered paths were rejected only after context discovery.
- Green: repository-relative path validation now runs before context discovery.

One initial ownership hypothesis was wrong. Moving shared files into feature
ownership broke the existing integration-owner assignment invariant. The
registry now keeps shared files integration-owned and registers only the new
coding-workflow files as feature-owned.

Independent review of revision
`d0a43bf019601c09579d3e27496e5e2a92ec9ce5` found three major issues:

- symlinked writable paths could resolve outside the repository;
- context hashing could race with a worktree change after the clean check;
- read-only modes received write scope while implementation mode prohibited
  repository changes.

Implementation resumed after review. The command now checks resolved-path
containment before context discovery, reads registry and context bytes from the
recorded Git revision, rechecks repository state before publication, and
derives assignment permissions from the selected mode. Focused regression
tests cover each finding.

Independent review of revision
`d13f4bd489d8c281dca77c6ed0c9696be68ab8aa` found a remaining publication
race plus two gaps in the shared assignment validator. Implementation resumed
again:

- repository state is rechecked inside the run lock before and after
  publication, with narrow rollback of an unchanged just-created run;
- assignment validation now rejects resolved paths outside the repository;
- assignment validation now requires empty writable paths for read-only modes;
- a missing committed workstream registry now produces a controlled CLI error.

Independent review of revision
`5b5da0ddc1d835dd1f7120b52bbdea95d7e0f289` found that separate final Git
observations could miss a clean commit and that the standalone assignment
command accepted dirty worktrees. Implementation resumed:

- coding-run publication and assignment dispatch now read branch, revision,
  and cleanliness from one Git status snapshot;
- the assignment command rejects dirty worktrees before validation;
- write-mode tests cover both `experiment` and `implementation`;
- the README names the required `nahmad/<name>-codex` branch form.

Independent review of revision
`4e20d6ef63c60357c84af3771030e94c1d577340` found a final assignment
validation race, acceptance of noncanonical registry files, and expired
idempotent retries. Implementation resumed:

- assignment validation reloads the final repository snapshot before success;
- the command requires the canonical repository registry path and reads its
  committed bytes from the assignment revision;
- identical existing runs remain recoverable after their review date, while
  new expired runs remain invalid.

Independent review of revision
`9c694bf3a40d22f8e6c4356046bbbf4c2391e764` found that standalone assignment
validation did not require nested instructions governing writable paths.
Implementation resumed:

- assignment generation and validation now share one governing-instruction
  discovery function;
- dispatch rejects assignments missing nested `AGENTS.md` files;
- the tracked meeting assignment example includes its governing vault
  instructions;
- a regression test proves dispatch reads committed registry bytes even when
  the working-tree file is hidden with `assume-unchanged`.

Independent review of revision
`e149f9fd2aee92ba37d88882a993c00fd8a8fbfe` found that nested instruction
discovery still read the working tree and missed directory-owned instructions.
Implementation resumed:

- governing instructions are discovered from the committed Git tree at the
  assignment revision;
- hidden or deleted working-tree instruction files fail required-context
  validation;
- directory write scopes load an `AGENTS.md` within the directory;
- `docs/agent-context.md` ownership moved to `coding-workflow` to match this
  branch's change attribution.

Independent review of revision
`968183905ed1a421e99ca79069ee66668985683b` found that an
`assume-unchanged` context file could retain its path but change its bytes.
Implementation resumed:

- assignment validation compares every working context file with its bytes at
  the recorded revision;
- `code start` repeats that comparison inside the run lock before and after
  publication;
- standalone dispatch repeats context-byte validation after its final
  repository snapshot.

Independent review of revision
`4280d61ca302f34b2d931a2dc9e38111c2dbd8bb` found that a non-context commit
could land during the final context comparison. Implementation resumed:

- `code start` repeats its coherent repository snapshot after the final
  context comparison and rolls back a stale new run;
- standalone dispatch repeats the same snapshot after its final context
  comparison before reporting success.

Launch implementation evidence:

- Red: no launch module or dry-run command existed.
- Green: dry-run previews task, project inference, worktree, model, and sandbox
  without contacting Codex or changing the run.
- Red: confirmed launch had no durable task metadata path.
- Green: verified thread, turn, project, worktree, model, and instruction
  sources are written atomically.
- Red: the app-server adapter and stale-assignment gate did not exist.
- Green: protocol tests cover initialize, thread creation, naming, opening
  turn, notifications, and exact pre-launch validation.
- Red: retries contacted launch preparation, and failed project verification
  discarded task identity.
- Green: retries return the recorded task, while mismatched or partial tasks
  enter `launch-needs-review` with recovery metadata.

Independent review of revision
`df500c0c54d041973c7a2fbb712e8a03aa3cbf67` found five major launch risks:
unbounded RPC reads, incomplete partial-task recovery, no durable pre-effect
intent, repository drift during app-server communication, and unverified
effective model or sandbox. Implementation resumed:

- every RPC response has a 30-second deadline;
- launch writes `launching` before app-server contact and blocks automatic
  duplicate retries after an interrupted attempt;
- thread identity is preserved before optional project, worktree, naming, or
  turn validation;
- repository and assignment validation runs immediately before and after the
  opening turn request;
- returned effective model and sandbox must match the preview;
- dry-run performs the same pre-launch validation as confirmed launch.

Independent review of revision
`a0a84a1360afb264d89e46a5294a939ea1c795ee` found five remaining launch
risks: notification-reset RPC timeouts, unverified saved-project identity,
task identity not persisted early enough, pre-thread failures blocked from
retry, and a schema error in `launching`. Implementation resumed:

- app-server output is drained by daemon readers and each RPC uses one absolute
  deadline, independent of notifications or text buffering;
- the experimental project API resolves one saved project from repository and
  worktree roots, passes its ID to `thread/start`, and verifies the response;
- the durable `launching` record receives the thread ID immediately after
  `thread/start`;
- failures known to occur before thread creation enter `launch-retryable`;
- cleanup errors cannot replace the original launch result;
- schema conditions now distinguish intent, retryable failure, partial
  recovery, and completed launch.

Independent review of revision
`664cc69ca1674efb18b2440c9c7f0ff682a70e95` found two major and two minor
recovery issues: pre-thread pipe errors were not retryable, cleanup could
replace success, final persistence errors were uncontrolled, and project
discovery stopped at 100 projects. Implementation resumed:

- pipe writes become controlled app-server errors and remain retryable before
  `thread/start`;
- all proxy cleanup failures are secondary and cannot replace the launch
  result;
- final persistence failure writes `launch-needs-review` from the already
  durable thread identity when storage recovers;
- project discovery follows cursor pagination while preserving request order.

Independent review of revision
`79b6b5edacba40caa56c7be3beb822b67f5b0215` found two major issues:
project matching admitted unrelated sibling worktrees, and repeated main-record
failure could lose the thread ID. Implementation resumed:

- project matching now considers only the target and primary Git worktrees;
- `launch-recovery.json` records thread identity independently immediately
  after `thread/start`;
- repeated `coding-run.json` failures return a controlled error that points to
  the recovery file rather than losing the task identity.

## Known Gaps

- No skill or playbook has been qualified for the pilot.
- App-server instruction sources are recorded, but full agent context
  acknowledgement and checkpoint capture remain unavailable.
- JIRA syntax is validated, but issue title, URL, and status remain unverified.
- Mode transitions and TDD, verification, review, closeout, and PR-draft
  evidence updates remain manual future slices.
- No PR-draft workflow or JIRA verification gate exists.
- The coding-run JSON schema is not executed by a general schema validator.
  Behavior tests check the generated record directly, so schema drift remains
  a minor review risk.
- The app-server adapter is protocol-tested with deterministic fakes. A live
  Codex project-placement trial remains pending exact owner approval.

## Write Ownership

The registry records the bounded integration-owner transfer for this slice.
Do not widen the paths or add another coding-workflow capability without an
accepted behavior and test interface.
