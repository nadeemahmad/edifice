"""Validate active agent assignments against repository workstream ownership."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import cast

ALLOWED_MODES = {
    "research",
    "experiment",
    "design",
    "implementation",
    "verification",
    "review",
}
ALLOWED_LEARNING_LEVELS = {"brief", "understand", "practice"}
READ_ONLY_MODES = {"research", "design", "verification", "review"}
REQUIRED_FIELDS = {
    "schema_version",
    "assignment_kind",
    "assignment_id",
    "workstream",
    "mode",
    "learning_level",
    "base_revision",
    "branch",
    "worktree",
    "objective",
    "context_paths",
    "writable_paths",
    "required_checks",
    "prohibited_effects",
    "completion_criteria",
}


class AssignmentValidationError(ValueError):
    """An active assignment violates the repository ownership contract."""


def main(argv: list[str] | None = None) -> int:
    """Validate an assignment against the current repository checkout."""
    parser = argparse.ArgumentParser()
    parser.add_argument("assignment", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    arguments = parser.parse_args(argv)
    repository_root = arguments.repository.resolve()
    branch, revision, working_tree_clean = _repository_state(repository_root)
    try:
        if not working_tree_clean:
            raise AssignmentValidationError("Repository working tree is not clean.")
        canonical_registry_path = (
            repository_root / "docs" / "workstreams" / "registry.json"
        )
        if arguments.registry.resolve() != canonical_registry_path:
            raise AssignmentValidationError(
                "Registry path must be the canonical repository registry."
            )
        assignment = _load_json(arguments.assignment)
        registry = _load_registry_at_revision(repository_root, revision)
        validated = validate_agent_assignment(
            assignment=assignment,
            registry=registry,
            repository_root=repository_root,
            expected_branch=branch,
            expected_revision=revision,
        )
        final_branch, final_revision, final_working_tree_clean = _repository_state(
            repository_root
        )
        if (
            final_branch != branch
            or final_revision != revision
            or not final_working_tree_clean
        ):
            raise AssignmentValidationError(
                "Repository changed during assignment validation."
            )
    except (AssignmentValidationError, OSError, json.JSONDecodeError) as error:
        print(f"Invalid assignment: {error}", file=sys.stderr)
        return 1
    print(f"Valid active assignment: {validated['workstream']}")
    return 0


def validate_agent_assignment(
    *,
    assignment: object,
    registry: object,
    repository_root: Path,
    expected_branch: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, object]:
    """Validate one active assignment and return its typed mapping."""
    typed_assignment = _require_mapping(
        assignment,
        "Assignment must be a JSON object.",
    )
    if set(typed_assignment) != REQUIRED_FIELDS:
        raise AssignmentValidationError("Assignment fields do not match schema.")
    if typed_assignment.get("schema_version") != 1:
        raise AssignmentValidationError("Unsupported assignment schema version.")
    if typed_assignment.get("assignment_kind") != "active":
        raise AssignmentValidationError("Only active assignments may be dispatched.")

    assignment_id = _require_string(typed_assignment, "assignment_id")
    workstream_id = _require_string(typed_assignment, "workstream")
    mode = _require_string(typed_assignment, "mode")
    learning_level = _require_string(typed_assignment, "learning_level")
    base_revision = _require_string(typed_assignment, "base_revision")
    branch = _require_string(typed_assignment, "branch")
    worktree = _require_string(typed_assignment, "worktree")
    _require_string(typed_assignment, "objective")

    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", assignment_id):
        raise AssignmentValidationError("Invalid assignment ID.")
    if mode not in ALLOWED_MODES:
        raise AssignmentValidationError(f"Invalid assignment mode: {mode}")
    if learning_level not in ALLOWED_LEARNING_LEVELS:
        raise AssignmentValidationError(
            f"Invalid assignment learning level: {learning_level}"
        )
    if not re.fullmatch(r"[0-9a-f]{40}", base_revision):
        raise AssignmentValidationError("Active assignment has an invalid revision.")
    if not re.fullmatch(r"nahmad/.+-codex", branch):
        raise AssignmentValidationError("Active assignment has an invalid branch.")
    assignment_worktree = Path(worktree)
    if not assignment_worktree.is_absolute():
        raise AssignmentValidationError("Active assignment worktree must be absolute.")
    if assignment_worktree.resolve() != repository_root.resolve():
        raise AssignmentValidationError(
            f"Assignment worktree does not match repository: {assignment_worktree}"
        )
    if expected_branch is not None and branch != expected_branch:
        raise AssignmentValidationError(
            f"Assignment branch mismatch: expected {expected_branch}, got {branch}"
        )
    if expected_revision is not None and expected_revision != base_revision:
        raise AssignmentValidationError(
            "Assignment revision does not match the current revision."
        )

    typed_registry = _require_mapping(
        registry,
        "Workstream registry must be a JSON object.",
    )
    if typed_registry.get("schema_version") != 1:
        raise AssignmentValidationError("Unsupported registry schema version.")
    workstreams_value = typed_registry.get("workstreams")
    if not isinstance(workstreams_value, list):
        raise AssignmentValidationError("Registry workstreams must be a list.")
    workstreams = {
        _require_string(workstream, "id"): workstream
        for value in cast(list[object], workstreams_value)
        for workstream in [
            _require_mapping(value, "Registry workstream must be an object.")
        ]
    }
    workstream = workstreams.get(workstream_id)
    if workstream is None:
        raise AssignmentValidationError(f"Unknown workstream: {workstream_id}")

    owned_paths = set(_require_string_list(workstream, "owned_paths"))
    integration_paths = set(
        _require_string_list(typed_registry, "integration_owned_paths")
    )
    context_paths = _require_string_list(typed_assignment, "context_paths")
    writable_paths = _require_string_list(typed_assignment, "writable_paths")
    if mode in READ_ONLY_MODES and writable_paths:
        raise AssignmentValidationError(
            f"Read-only assignment mode cannot declare writable paths: {mode}"
        )
    for field in (
        "required_checks",
        "prohibited_effects",
        "completion_criteria",
    ):
        _require_string_list(typed_assignment, field)

    for path in writable_paths:
        _validate_repository_path(
            path,
            repository_root=repository_root,
            label="Writable path",
        )
        if path in integration_paths:
            raise AssignmentValidationError(
                f"Writable path is integration-owned: {path}"
            )
        if path not in owned_paths:
            raise AssignmentValidationError(
                f"Writable path is not owned by workstream {workstream_id}: {path}"
            )

    required_context = {
        "AGENTS.md",
        "docs/agent-context.md",
        "docs/engineering/owner-practices.md",
        _require_string(workstream, "context"),
    }
    required_context.update(
        governing_instruction_paths(
            repository_root,
            base_revision,
            writable_paths,
        )
    )
    missing_context = sorted(required_context - set(context_paths))
    if missing_context:
        raise AssignmentValidationError(
            "Assignment is missing governing instructions or required context: "
            + ", ".join(missing_context)
        )

    for path in context_paths:
        _validate_repository_path(
            path,
            repository_root=repository_root,
            label="Context path",
        )
        if not (repository_root / path).is_file():
            raise AssignmentValidationError(
                f"Assignment context path is unavailable: {path}"
            )
    return typed_assignment


def governing_instruction_paths(
    repository_root: Path,
    revision: str,
    writable_paths: list[str],
) -> list[str]:
    """Return nested instruction files governing the declared write scope."""
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "--full-tree", revision],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise AssignmentValidationError(
            f"Cannot inspect repository instructions at revision {revision}."
        ) from error
    committed_paths = set(result.stdout.splitlines())
    instruction_paths: set[str] = set()
    for writable_path in writable_paths:
        path = Path(writable_path)
        for candidate_root in [*path.parents[::-1], path]:
            instruction_path = candidate_root / "AGENTS.md"
            if instruction_path.as_posix() in committed_paths:
                instruction_paths.add(instruction_path.as_posix())
    return sorted(instruction_paths)


def _require_mapping(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssignmentValidationError(message)
    return cast(dict[str, object], value)


def _require_string(mapping: object, field: str) -> str:
    typed_mapping = _require_mapping(mapping, f"{field} container must be an object.")
    value = typed_mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AssignmentValidationError(f"Assignment field must be text: {field}")
    return value


def _require_string_list(mapping: object, field: str) -> list[str]:
    typed_mapping = _require_mapping(mapping, f"{field} container must be an object.")
    value = typed_mapping.get(field)
    if not isinstance(value, list):
        raise AssignmentValidationError(f"Assignment field must be a list: {field}")
    items = cast(list[object], value)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise AssignmentValidationError(f"Assignment list must contain text: {field}")
    typed_items = cast(list[str], items)
    if len(typed_items) != len(set(typed_items)):
        raise AssignmentValidationError(f"Assignment list contains duplicates: {field}")
    return typed_items


def _validate_repository_path(
    value: str,
    *,
    repository_root: Path,
    label: str,
) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise AssignmentValidationError(f"Unsafe repository path: {value}")
    try:
        (repository_root / path).resolve().relative_to(repository_root)
    except ValueError as error:
        raise AssignmentValidationError(
            f"{label} resolves outside repository: {value}"
        ) from error


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_registry_at_revision(repository_root: Path, revision: str) -> object:
    try:
        result = subprocess.run(
            [
                "git",
                "show",
                f"{revision}:docs/workstreams/registry.json",
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise AssignmentValidationError(
            f"Cannot read canonical registry at revision {revision}."
        ) from error


def _repository_state(repository_root: Path) -> tuple[str, str, bool]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v2", "--branch"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    branch = ""
    revision = ""
    working_tree_clean = True
    for line in result.stdout.splitlines():
        if line.startswith("# branch.head "):
            branch = line.removeprefix("# branch.head ")
        elif line.startswith("# branch.oid "):
            revision = line.removeprefix("# branch.oid ")
        elif not line.startswith("# "):
            working_tree_clean = False
    if branch == "(detached)":
        branch = ""
    return branch, revision, working_tree_clean


if __name__ == "__main__":
    raise SystemExit(main())
