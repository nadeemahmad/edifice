---
type: owner-practices
created: 2026-09-07
ownership: human
---

# Owner Practices

## Judgment

- Maintain healthy skepticism about every claim.
- Verify assumptions and distinguish evidence from inference.
- Prefer the simplest design that satisfies the actual workflow.
- Reuse established solutions when they fit.

## Code

- Use clear names and small focused functions.
- Keep comments for context that code cannot express.
- Follow repository conventions.
- Avoid unrelated refactoring.

## Tests

- Test observable behavior through agreed interfaces.
- Use test-first vertical slices for behavior changes and bug fixes.
- Keep setup, execution, and assertions clear.
- Use real owned files and databases where practical.

## Debugging

1. State a causal hypothesis.
2. Change one variable.
3. Verify the effect disappears.
4. Restore the cause and verify the effect returns when practical.
5. Record the result.
6. Reject a failed hypothesis and form another.

Correlation alone is not proof.

## Review

- Lead with concrete findings ordered by severity.
- Ground findings in exact behavior and evidence.
- Do not invent issues to make a review look useful.
- State omitted tests and residual risk.
