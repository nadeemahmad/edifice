# Integration Ownership

## Purpose

Prevent concurrent feature work from colliding in command registration,
top-level documentation, vault governance, and other shared files.

## Integration-Owned Files

The authoritative list lives in `docs/workstreams/registry.json`. It currently
includes:

- `README.md`
- `src/edifice/cli.py`
- `src/edifice/context_worker.py`
- `tests/test_doctor_cli.py`
- root vault-template instructions
- shared system guides
- the work home page

Only the integration owner edits these files unless a workstream assignment
explicitly transfers one path.

## Feature-Agent Contract

A feature agent:

1. Changes only its registered owned paths.
2. Tests behavior through the existing CLI or module interface.
3. Records required shared-file changes in its closeout.
4. Returns a narrow patch or exact insertion request when shared integration is
   needed.
5. Does not register commands, rewrite top-level documentation, or update
   shared schemas concurrently with another feature agent.

## Integration Workflow

The integration owner:

1. Reviews the feature objective, tests, and closeout.
2. Confirms the feature-owned diff contains no shared files.
3. Applies command registration and shared documentation.
4. Runs focused feature tests.
5. Runs the complete deterministic checks.
6. Records the integration revision in the workstream context.

## CLI Composition

`src/edifice/cli.py` remains the current Click composition module. Feature
behavior stays in feature-owned modules such as `inbox.py`, `work_task.py`,
`meeting_note.py`, and `document_review.py`.

The accepted future shape is:

```text
src/edifice/
  cli.py
  runtime.py
  commands/
    inbox.py
    work_task.py
    meeting.py
    document_review.py
```

`cli.py` would retain root options, shared runtime construction, command
registration, and genuinely shared commands. Each feature command module would
own argument adaptation and invoke its existing feature module.

## Refactor Trigger

Do not perform the split merely to reduce file length. Enter design mode for
the refactor when one of these occurs:

- two active workstreams require concurrent edits to `cli.py`;
- another substantial command group is added;
- integration conflicts recur after the ownership protocol is followed;
- command tests cannot exercise a feature without importing unrelated command
  implementations;
- shared runtime behavior needs a second real caller.

Until then, integration ownership prevents collisions without introducing a
large behavior-preserving rewrite.
