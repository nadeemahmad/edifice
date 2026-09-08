# Agent rules

Read these files before substantive work:

- `00-system/operating-manual.md`
- `00-system/soul.md`
- `00-system/schema.md`
- `00-system/workflows.md`
- `00-system/work-context-policy.md`
- `00-system/engineering/owner-practices.md`

## Permissions

- Read operational notes needed for the active task.
- Write only to `10-personal/operations`, `10-personal/ai`,
  `10-personal/artifacts`, `20-work`, and `01-inbox/inbox.md`, subject to the
  applicable nested rules.
- Treat `10-personal/notes` as human-owned and read-only.
- Treat `90-archive` as read-only.
- Preserve raw captures and provenance.
- Use the `edifice` command for captures.
- Use `edifice pdf add` for exact local PDF copies and catalog updates.
- Do not enable synchronization while `20-work` contains local work context.
- Do not store secrets, credentials, restricted personal data, or uncontrolled
  bulk work exports.
- Do not start background jobs or mutate external systems.
- Ask for exact approval before protected edits, deletion, publication, or
  another irreversible action.
- Conversation history is not authoritative state.
