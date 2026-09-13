---
id: repository-organization
status: active
mode: implementation
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

## Known Gaps

- Complete repository verification and independent final review remain.
- The first real concurrent feature assignment has not yet exercised the
  worktree protocol.

Resolved during this workstream:

- A machine-readable workstream registry now exists.
- Shared files have one documented integration owner.
- CLI command modularization has an explicit design and evidence trigger.
- Existing dirty work is separated into intentional commits.
- The fresh-agent orientation exercise passed.
- Every changed branch path must have registered ownership.
- Active assignments receive semantic validation against workstream ownership,
  integration-owned paths, required context, worktree, branch, and revision.

## Write Ownership

The integration agent owns repository context and shared-file reconciliation.
Feature agents must not edit these files without an explicit assignment.
