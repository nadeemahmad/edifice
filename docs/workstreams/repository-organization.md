---
id: repository-organization
status: committed
mode: review
verified_revision: 4bef93664e6fb8b626fa4a1ebee08be5ef594d27
---

# Repository Organization

## Objective

Create a repository-owned instruction and context system that lets fresh agents
work on separate Edifice workstreams without relying on conversation history.

## Current State

- The source repository has a root `AGENTS.md`.
- Vault-template and source-repository instructions have distinct scopes.
- Feature work is separated into four checkpoint commits and one shared
  integration commit.
- The registry assigns shared files to one integration owner.
- A verified recovery snapshot exists outside the repository.
- A fresh read-only agent reconstructed its assignment, authority, branch,
  revision, and safety constraints without conversation history.
- Independent review at the verified revision found no high or medium defects.

## Proposed Owned Files

- `AGENTS.md`
- `docs/agent-context.md`
- `docs/workstreams/`
- `docs/engineering/`

## Shared Files

- Existing feature modules and tests are read-only inputs.
- Feature-owned files should not change during repository organization unless
  separation or verification requires it.

## Dependencies

- Current Git-state preservation.
- Owner engineering-practice reconciliation.
- Deliberate commit separation.

## Verification

- Validate all context files and paths.
- Run a clean-agent orientation exercise.
- Run full deterministic repository checks after organization.

Completed evidence:

- Full pytest: 118 passed.
- Ruff lint and format: passed.
- Strict Pyright: 0 errors or warnings.
- Branch and working tree: clean.
- Independent focused checks: 23 passed.
- Independent findings: no high or medium defects.

## Known Gaps

- The first real concurrent feature assignment has not yet exercised the
  worktree protocol.
- The low-severity work-task `primary_anchor` decision remains open.
- Document-review add and synthesis lack one shared cross-process lock and
  complete audit contract.
- Inbox recovery assumes one intact canonical source link when repairing a
  damaged destination.

Resolved during this workstream:

- A machine-readable workstream registry now exists.
- Shared files have one documented integration owner.
- CLI command modularization has an explicit design and evidence trigger.
- Existing dirty work is separated into intentional commits.
- The fresh-agent orientation exercise passed.
- Every changed branch path must have registered ownership.
- Active assignments receive semantic validation against workstream ownership,
  integration-owned paths, required context, worktree, branch, and revision.
- Independent final review found no high or medium defects.

## Promotion State

The organization branch is committed and review-ready. It has not been merged
to `main`, pushed to a remote, or applied to the live vault.

## Write Ownership

The integration agent owns repository context and shared-file reconciliation.
Feature agents must not edit these files without an explicit assignment.
