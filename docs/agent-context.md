# Edifice Agent Context

## Purpose

Edifice is a local Obsidian-centered operating system. The source repository
implements deterministic capture, work context, document review, PDF,
migration, meeting, and task workflows. The live vault remains a separate
operating environment.

## Repository

- Root: `/Users/nahmad/Developer/projects/edifice`
- Language: Python 3.13 and 3.14
- CLI: Click
- Tests: pytest
- Lint and format: Ruff
- Type checking: strict Pyright
- Git remote: none

## Authority

Use this order:

1. Company policy and verified identity restrictions.
2. Root and nested `AGENTS.md` files.
3. Repository conventions and deterministic checks.
4. `docs/engineering/owner-practices.md`.
5. The assigned workstream record.
6. Accepted playbooks and runtime-specific skills.

The design record and current operational handoff provide historical and
accepted-decision evidence. Conversation history does not replace repository
state.

## Workstreams

The machine-readable index is `docs/workstreams/registry.json`. Human context
lives in the corresponding Markdown file:

- `document-review`
- `work-task`
- `inbox-routing`
- `meeting-notes`
- `coding-workflow`
- `repository-organization`

Read only the workstream context needed for the assignment. Do not load broad
personal or work content merely because it is accessible.

## Shared Integration Files

The registry lists files reserved for the integration owner. Important current
hotspots include:

- `README.md`
- `src/edifice/cli.py`
- `tests/test_doctor_cli.py`
- `vault-template/00-system/getting-started.md`
- `vault-template/00-system/operating-manual.md`
- `vault-template/00-system/schema.md`
- `vault-template/00-system/work-context-policy.md`
- `vault-template/00-system/workflows.md`
- `vault-template/20-work/home.md`

Feature agents should return required shared-file changes as recommendations or
small patches unless their assignment explicitly grants integration ownership.
The integration procedure and deferred CLI composition design are recorded in
`docs/engineering/integration-ownership.md`.

## Source And Live State

- `vault-template` contains source-controlled vault defaults.
- `/Users/nahmad/Obsidian/edifice` is the live vault.
- `/Users/nahmad/.local/bin/edifice` runs the canonical source checkout.
- Uncommitted changes in the canonical checkout are therefore live through the
  installed command.
- Do not mutate the live vault, launcher, audit records, migrations, Drive, or
  an external system without an exact approved effect.

## Starting An Assignment

1. Confirm the workstream ID and objective.
2. Confirm the active work mode.
3. Read the workstream context and listed dependencies.
4. Inspect the assigned worktree and existing changes.
5. Confirm writable paths and integration-owned files.
6. Name the behavior and test interface before implementation.
7. Run the focused baseline check.

## Closing An Assignment

Return:

- files changed;
- behavior and decisions;
- failing and passing evidence;
- complete verification performed;
- findings and unresolved risk;
- shared-file integration requested;
- next action.

Do not mark a workstream complete merely because one agent turn ended.

Concurrent assignments follow
`docs/engineering/parallel-agent-protocol.md` and return the structured
closeout in `docs/engineering/agent-closeout-template.md`.
