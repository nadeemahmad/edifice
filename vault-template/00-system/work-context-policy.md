---
type: work-context-policy
created: 2026-09-08
ownership: human
---

# Work Context Policy

## Current mode

Work context may persist under `20-work` while the Edifice vault remains local
and Obsidian Sync is disabled.

This is a temporary local operating mode, not permission to upload work data to
personal cloud storage.

## Allowed

- Active-task context required to make progress.
- JIRA keys, links, titles, status, and relationships.
- Repository paths, revisions, relevant files, tests, and local findings.
- Links and approved excerpts from Docs, Drive, Manuals, Slack, email, or
  Calendar when required for the task.
- Owner notes, decisions, blockers, next actions, and verified summaries.
- Read-only worker reports with source and verification metadata.

## Prohibited

- Passwords, tokens, cookies, private keys, recovery codes, or credentials.
- Customer, member, employee, talent, or partner restricted personal data.
- Security incident details, vulnerabilities, pentest results, or restricted
  security architecture without an approved storage path.
- Uncontrolled mailbox, Drive, JIRA, Slack, repository, or document exports.
- Work context copied merely because it is technically accessible.
- External mutations without the separate identity, approval, audit, and
  read-back gates.

## Required metadata

Every durable work-context note identifies:

- authoritative source and stable link or locator;
- relevant JIRA issue and repository when applicable;
- data classification;
- why local persistence is needed;
- verification date;
- owner next action;
- expiry or review condition when the context is temporary.

## Sync gate

`edifice doctor` must pass before any Sync change.

Before personal Sync is enabled:

1. Inventory every item under `20-work`.
2. Move work context to an approved work-only location or delete it through an
   exact reviewed cleanup.
3. Verify `20-work` contains no work data.
4. Re-run doctor and a separate Sync qualification.

Encryption does not override this rule.
