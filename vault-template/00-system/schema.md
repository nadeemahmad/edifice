---
type: schema
created: 2026-09-07
---

# Schema

## Managed notes

Managed operational notes contain:

```yaml
id: <type-prefixed-uuid>
type: <registered-type>
schema_version: 1
created: YYYY-MM-DD
status: <type-specific-status>
```

Kernel v0 registers:

- `area`
- `direction`
- `outcome`
- `project`
- `question`
- `review`

Tasks remain Markdown checkboxes in the note that owns their context.

## Ownership

- `10-personal/operations`: agent-writeable operational state.
- `10-personal/notes`: human-owned and agent-readable.
- `10-personal/ai`: agent-writeable research and suggestions.
- `01-inbox/inbox.md`: append-only captures and reversible routing.
- `00-system`: protected governance and configuration.
- `90-archive`: read-only except for approved restore or retention work.

## Naming

- Generated vault paths and Markdown filenames use lowercase kebab-case.
- Python uses snake_case.
- Human-facing headings use normal title text.
- Conventional tool files such as `AGENTS.md` retain their required names.
