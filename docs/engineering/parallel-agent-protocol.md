# Parallel Agent Protocol

## Preconditions

Do not dispatch concurrent writers until:

- the integration branch is clean;
- the base revision has passed required checks;
- the workstream registry is valid;
- every assignment has disjoint writable paths;
- shared files remain assigned to the integration owner.

Read-only research, verification, and review may run concurrently when their
context and external-system permissions are independent.

## Assignment

Each agent receives a JSON assignment matching
`agent-assignment.schema.json`.

Tracked examples use `assignment_kind: example` and are never executable
assignments. A real dispatch uses `assignment_kind: active`, names an accepted
behavior, and records the exact verified base revision.

The assignment names:

- one workstream;
- one active work mode;
- one learning level;
- the exact base revision;
- its branch and worktree;
- one bounded objective;
- required context;
- writable paths;
- required checks;
- prohibited effects;
- completion criteria.

Do not rely on a conversational request to widen the assignment. Update the
durable assignment first.

## Worktree And Branch

Create one worktree per writing agent from the verified integration revision:

```text
git worktree add \
  /Users/nahmad/Developer/worktrees/edifice-<workstream> \
  -b nahmad/edifice-<workstream>-codex \
  <base-revision>
```

The canonical checkout remains the integration worktree and installed-launcher
source. Feature worktrees must not change the live launcher or live vault.

Worktrees may use the canonical environment binaries without installing new
dependencies:

```text
/Users/nahmad/Developer/projects/edifice/.venv/bin/python -m pytest
/Users/nahmad/Developer/projects/edifice/.venv/bin/ruff check --no-cache .
```

Run commands from the feature worktree so repository-relative source and tests
come from that worktree.

## Execution

At startup, the agent reports:

- assignment ID and workstream;
- base revision and branch;
- active mode and learning level;
- writable and prohibited paths;
- focused baseline result;
- any contradiction in the supplied context.

The agent stops and reports when:

- it needs a shared integration file;
- the base revision or assignment is stale;
- another workstream owns a required path;
- policy, identity, or approval is unclear;
- the accepted design is invalidated;
- required verification cannot run.

## Shared Changes

Feature agents do not edit integration-owned files. Their closeout describes
the required command registration, documentation, schema, or shared-rule
change with enough detail for the integration owner to apply it.

The integration owner may temporarily grant a shared path to one assignment.
That transfer must be explicit and may not overlap another active assignment.

## Closeout

Use `agent-closeout-template.md`. The closeout records:

- objective and result;
- changed files;
- mode transitions;
- decisions and assumptions;
- failing and passing evidence;
- verification performed;
- findings and residual risk;
- integration requests;
- unresolved work and next action.

The agent does not claim workstream completion. The integration owner reviews
the result, applies shared changes, runs complete verification, and updates the
workstream state.

## Integration

Integrate one feature branch at a time:

1. Confirm its base and assignment.
2. Inspect its full diff and closeout.
3. Reject out-of-scope changes.
4. Apply or reconcile shared-file requests.
5. Run focused checks.
6. Run complete deterministic checks.
7. Perform independent review when required.
8. Record the integration revision in the workstream context.

Delete or archive branches and worktrees only after useful evidence is
preserved and the owner approves destructive cleanup.
