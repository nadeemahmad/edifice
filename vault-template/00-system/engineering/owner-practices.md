---
type: owner-practices
schema_version: 1
created: 2026-09-07
ownership: human
canonical: true
---

# Owner Engineering Practices

## Purpose

These practices define the owner's durable, cross-repository engineering
preferences. They fill gaps without weakening company policy, security rules,
repository instructions, or deterministic checks.

Agents may propose changes, but the owner approves every modification to this
file.

## Precedence

Apply instructions in this order:

1. Company policy, security rules, and verified identity restrictions.
2. Repository and path-specific instructions and deterministic checks.
3. These owner engineering practices.
4. Accepted work-mode playbooks.
5. Runtime-specific skills and prompts.

When two rules conflict, follow the higher authority and record the conflict.
Do not silently combine incompatible requirements.

## Judgment

- Maintain healthy skepticism about every claim, including owner and agent
  claims.
- Verify assumptions and distinguish observed facts, documented claims,
  hypotheses, and inferences.
- Prefer the simplest design that satisfies the actual workflow.
- Do not infer completion from activity, code volume, test count, or agent
  confidence.
- State uncertainty and unavailable evidence instead of manufacturing a
  plausible answer.

Evidence:

- Consequential conclusions cite code, tests, commands, documentation, or
  observed behavior.
- Closeout reports identify assumptions and residual uncertainty.

## Design

- Material changes require an accepted lightweight design before
  implementation.
- Narrow changes within an established interface may proceed directly after
  recording the behavior and test interface.
- Prefer deep modules with small interfaces and substantial behavior behind
  them.
- Add a module or seam only when it removes real complexity, supports an
  actual variation, or creates a meaningful test interface.
- Preserve existing module ownership and repository conventions.
- Record realistic alternatives when the choice has material tradeoffs.
- Include failure behavior, compatibility, migration, rollback, privacy, and
  operational effects when relevant.

Evidence:

- The accepted design identifies the objective, constraints, non-goals,
  selected interface, rejected alternatives, and first implementation slice.
- Material discoveries that invalidate the design return the work to design
  or experiment mode.

## Qualified Reuse

Inspect candidates in this order:

1. Existing repository code, helpers, conventions, and dependencies.
2. Approved organization libraries, platforms, templates, and paved roads.
3. Standard-library and existing-framework capabilities.
4. Qualified external dependencies and reference implementations.
5. A small custom implementation when prior options do not fit.

- Popularity and familiarity do not establish fit.
- Verify behavior, policy, licensing, maintenance, testability, and removal
  cost before adding a dependency.
- Do not create a shallow wrapper that merely repeats another interface.
- Record what was reused, what was rejected, and why custom work was needed.

## Code

Follow Clean Code principles in sympathy with the repository:

- Use clear and expressive names.
- Keep functions focused on one responsibility.
- Make control flow and state changes easy to follow.
- Keep comments for context the code cannot express.
- Do not add comments that narrate obvious code.
- Avoid unrelated refactoring and metadata churn.
- Prefer structured parsers and interfaces over ad hoc string manipulation.
- Keep changes within the modules and ownership implied by the objective.

Repository conventions take precedence when they explicitly choose a
different, coherent style.

## Tests And TDD

Observable behavior changes and bug fixes use test-first vertical slices.

For each slice:

1. Name one behavior and the interface where it will be observed.
2. Derive the expected result independently from the implementation.
3. Write the smallest test that fails for the intended reason.
4. Record the failing result.
5. Implement only enough behavior to satisfy the test.
6. Run the focused test and relevant regression checks.
7. Clean the implementation while the tests remain green.
8. Repeat with the next behavior.

Test design:

- Test through public or explicitly accepted internal interfaces.
- Prefer real owned files and databases in temporary environments.
- Use fakes for external systems.
- Mock only when the interaction itself is the behavior under test.
- Use expressive test names.
- Keep setup, execution, and assertions clear and minimal.
- Avoid tautological, implementation-coupled, and unnecessarily broad snapshot
  tests.
- Treat coverage as a diagnostic, not a target that substitutes for behavior.

Exceptions:

- Documentation, comments, formatting, and metadata-only changes use focused
  checks instead of artificial failing tests.
- Refactors begin from passing characterization or behavior tests.
- Experiments may defer production TDD, but promotion requires the normal test
  contract.
- Every exception records why TDD did not fit and the compensating evidence.

## Scientific Debugging

Never accept causation from correlation or the first observation.

1. State a falsifiable causal hypothesis.
2. Design a controlled test that changes one variable.
3. Remove or alter the suspected cause and verify the effect disappears.
4. Restore the cause and verify the effect returns when practical.
5. Record the commands, environment, and observed result.
6. If the hypothesis fails, say so explicitly and form another.
7. Repeat until the evidence supports a root cause or the remaining evidence
   is unavailable.

Begin bug fixes with a failing reproduction and preserve the final regression
test.

## Verification

- Verification applies to the exact intended revision and dependency state.
- Run focused tests before broader regression and repository-required checks.
- Prefer CI, a fresh worktree, or another independently reconstructed
  environment for PR-worthy changes.
- Distinguish passed, failed, skipped, unavailable, flaky, and not-applicable
  checks.
- Reproduce generated artifacts when freshness matters.
- Never claim a test or check passed without running it and inspecting the
  result.
- State untested conditions and the resulting risk.

A prior green run does not prove a later revision.

## Review

Every PR-worthy change receives independent read-only review after required
verification.

- Lead with findings ordered by severity.
- Ground each finding in exact behavior, evidence, and a narrow code location.
- Distinguish demonstrated defects from plausible risks and open questions.
- Focus on bugs, regressions, missing tests, failure handling, permissions,
  compatibility, and maintainability.
- Do not invent findings to make a review appear useful.
- Do not repeat style checks already enforced by deterministic tools.
- State omitted review areas and residual risk when there are no findings.

Review findings return to implementation, design, research, or experiment mode
as appropriate. The reviewer does not silently repair the implementation.

## Learning Intent

Material repository runs declare one learning level:

- `brief`: problem, important changes, tests, risks, and next action.
- `understand`: design, important code paths, dependencies, alternatives, test
  rationale, and remaining uncertainty.
- `practice`: prediction, questions, teach-back, tracing, reconstruction, or a
  small owner-completed exercise.

The owner may override the recommended level. A generated explanation does not
prove owner understanding.

## Pull Request Descriptions

Treat every pull request description as a concise briefing that helps a
reviewer understand and evaluate the change.

Before drafting:

- Inspect the final intended diff, commits, tests, linked JIRA issue, relevant
  design documents, and review findings.
- Never invent motivation, behavior, impact, tests, risks, or links.
- Follow the repository template when one exists.

Without a repository template, use:

1. `## What?`
2. `## Why?`
3. `## How?`
4. `## Testing?`
5. `## Screenshots` when useful
6. `## Anything Else?` when useful

Content:

- `What?` explains the net behavior and scope.
- `Why?` explains the problem and desired outcome without requiring the
  reviewer to open the ticket.
- `How?` identifies significant choices, dependencies, migrations, tradeoffs,
  and departures from established patterns.
- `Testing?` lists exact checks and results, plus untested conditions and risk.
- Screenshots or captured output should help assess visible behavior.
- `Anything Else?` contains reviewer focus, risks, rollout, compatibility,
  follow-up, debt, or meaningful alternatives.

JIRA and design links:

- Always capitalize JIRA as `JIRA`.
- Every GitHub pull request description contains at least one verified JIRA
  ticket link formatted as `[KEY: Ticket Title](URL)`.
- Never infer or fabricate the issue key, title, or URL.
- Do not prefix the link with `Relates to`, `Closes`, `Fixes`, or similar text
  unless the owner explicitly requests it.
- Include a descriptive design-document link when the document genuinely
  governs the change.
- Include the relevant JIRA and design links in every stacked pull request.

The owner approves the exact description before publication. Material changes
after approval require a refreshed draft.

## Exceptions And Changes

- Record the reason and compensating evidence for any exception.
- A runtime skill or agent preference may not weaken these practices.
- Owner edits to one run do not silently modify this file.
- Revise this file only from repeated evidence, an explicit owner preference,
  or a concrete conflict with repository practice.
