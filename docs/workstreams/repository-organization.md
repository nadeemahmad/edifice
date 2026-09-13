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

- The source repository has no root `AGENTS.md`.
- Vault-template instructions govern generated vault content, not source work.
- Several uncommitted workstreams overlap in `src/edifice/cli.py`, `README.md`,
  and the system guides.
- A verified recovery snapshot exists outside the repository.

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

- No machine-readable workstream registry exists.
- Shared-file integration ownership is not enforced.
- Existing dirty work has not been separated into intentional commits.

## Write Ownership

The integration agent owns repository context and shared-file reconciliation.
Feature agents must not edit these files without an explicit assignment.
