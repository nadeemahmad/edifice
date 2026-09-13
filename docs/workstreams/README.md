# Workstreams

`registry.json` is the machine-readable index. Each Markdown file contains the
human-readable objective, state, ownership, verification, and handoff context
for one workstream.

Agents receive one primary workstream. Concurrent writers use separate
worktrees and disjoint owned paths. Files listed under
`integration_owned_paths` remain with the integration owner.

Update a workstream record whenever its objective, ownership, accepted
decision, verification, blocker, or next action changes materially.
