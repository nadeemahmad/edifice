# Edifice Source Agent Rules

These rules govern work in the Edifice source repository. The nested
`vault-template/**/AGENTS.md` files govern generated vault content and do not
replace these source rules.

## Read First

Before substantive work:

1. Read `README.md`.
2. Read `docs/agent-context.md`.
3. Read `docs/engineering/owner-practices.md`.
4. Read the relevant file under `docs/workstreams/`.
5. Inspect `git status`, the current diff, and recent history.
6. Read every nested `AGENTS.md` governing files in the assigned write scope.

Conversation history is not authoritative project state.

## Instruction Precedence

1. Company policy, security rules, and verified identity restrictions.
2. Repository and path-specific instructions and deterministic checks.
3. Owner engineering practices.
4. Accepted work-mode playbooks.
5. Runtime-specific skills and prompts.

Fail closed when identity, policy, ownership, or approval is unclear.

## Workstream Ownership

- Every agent receives one workstream objective and explicit writable paths.
- Feature-owned files are listed in `docs/workstreams/<workstream>.md`.
- `README.md`, `src/edifice/cli.py`, and shared system guides are
  integration-owned unless the assignment explicitly includes them.
- Follow `docs/engineering/integration-ownership.md` for shared-file changes.
- Do not edit another active workstream's owned files.
- Use separate Git worktrees for concurrent write tasks.
- Branches created by Codex use `nahmad/` and end in `-codex`.

## Git Safety

- Preserve all existing tracked and untracked changes.
- Never reset, revert, restore, delete, stage, or commit unrelated work.
- Inspect the complete diff before staging.
- Attribute only changes made for the assigned workstream.
- Do not combine independent workstreams into one accidental commit.
- Do not create or update a pull request without exact owner approval.

## Source And Live Vault

- Source code and `vault-template` files live in this repository.
- The live vault at `/Users/nahmad/Obsidian/edifice` is a separate Git
  worktree and is not an implementation sandbox.
- Do not mutate the live vault, installed launcher, audit history, Drive,
  migration packages, or an external system unless the assignment names the
  exact effect and the owner approves it.
- Obsidian Sync remains disabled while governed work context is present.

## Engineering

- Follow the repository's established Python, Click, pytest, Ruff, and Pyright
  patterns.
- Prefer small interfaces with substantial behavior behind them.
- Reuse existing repository modules and standard-library facilities when they
  satisfy the requirement.
- Use clear names, focused functions, and comments only for context the code
  cannot express.
- Avoid unrelated refactoring.

## Testing And Debugging

- Test observable behavior through the same interface callers use.
- Behavior changes and bug fixes use test-first vertical slices.
- Bugs begin with a failing reproduction.
- State a causal hypothesis, change one variable, verify the effect
  disappears, restore the cause when practical, and verify the effect returns.
- Record a failed hypothesis instead of replacing it with a plausible story.
- Prefer real owned files and databases in temporary directories.
- Mock or fake only external systems and interactions.

## Verification

Run the focused tests first, then the complete required checks:

```text
.venv/bin/python -m pytest -p no:cacheprovider
.venv/bin/ruff check --no-cache .
.venv/bin/ruff format --check --no-cache .
.venv/bin/python .venv/bin/pyright
git diff --check
```

Report exact commands and results. State tests not run and residual risk.

## Completion

Before handing work back:

- Re-read the assigned workstream objective and write scope.
- Inspect the final diff for unrelated changes.
- Record changed files, verification, decisions, open questions, and follow-up.
- Do not claim implementation, verification, review, publication, or
  completion without the required evidence.
