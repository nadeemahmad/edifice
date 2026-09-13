"""Create durable records for governed coding runs."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

import click

from edifice.agent_assignment import (
    ALLOWED_LEARNING_LEVELS,
    ALLOWED_MODES,
    AssignmentValidationError,
    governing_instruction_paths,
    validate_agent_assignment,
)

CODING_RUN_DIRECTORY = Path("20-work/operations/coding-runs")
JIRA_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-[1-9][0-9]*$")
CLASSIFICATIONS = frozenset({"public", "netflix-internal", "netflix-confidential"})
READ_ONLY_MODES = frozenset({"research", "design", "verification", "review"})
REQUIRED_CHECKS = (
    ".venv/bin/python -m pytest -p no:cacheprovider",
    ".venv/bin/ruff check --no-cache .",
    ".venv/bin/ruff format --check --no-cache .",
    ".venv/bin/python .venv/bin/pyright",
    "git diff --check",
)
BASE_PROHIBITED_EFFECTS = (
    "Do not launch an agent.",
    "Do not mutate JIRA, GitHub, the live vault, or another external system.",
    "Do not install software, authenticate, push, or create a pull request.",
)
COMPLETION_CRITERIA = (
    "The accepted design is recorded.",
    "Behavior changes have test-first vertical-slice evidence.",
    "Required checks pass at the exact final revision.",
    "An independent read-only findings-first review is complete.",
    "A PR description draft uses verified JIRA and design evidence.",
)


@dataclass(frozen=True)
class CodingRunResult:
    slug: str
    run_path: Path
    assignment_path: Path
    created: bool


def start_coding_run(
    *,
    vault_root: Path,
    audit_root: Path,
    name: str,
    objective: str,
    jira_key: str,
    repository: Path,
    workstream_id: str,
    mode: str,
    learning_level: str,
    classification: str,
    review_on: date,
    persistence_reason: str,
) -> CodingRunResult:
    """Validate and persist one coding run without launching an agent."""
    normalized_name = _normalize_text(name, "Coding run name")
    slug = _slug(normalized_name)
    normalized_objective = _normalize_text(objective, "Objective")
    normalized_jira_key = _validate_jira_key(jira_key)
    normalized_mode = _validate_choice(mode, "mode", ALLOWED_MODES)
    normalized_learning_level = _validate_choice(
        learning_level,
        "learning level",
        ALLOWED_LEARNING_LEVELS,
    )
    normalized_classification = _validate_choice(
        classification,
        "classification",
        CLASSIFICATIONS,
    )
    normalized_persistence_reason = _normalize_text(
        persistence_reason,
        "Persistence reason",
    )
    created_at = _now()

    repository_root = _validate_repository(repository)
    branch, revision, working_tree_clean = _repository_state(repository_root)
    if not branch:
        raise click.ClickException("Repository must be on a named branch.")
    if not working_tree_clean:
        raise click.ClickException("Repository working tree must be clean.")

    try:
        registry_content = _git_bytes(
            repository_root,
            "show",
            f"{revision}:docs/workstreams/registry.json",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise click.ClickException(
            f"Workstream registry is unavailable at revision {revision}."
        ) from error
    registry = _load_mapping_bytes(
        registry_content,
        f"workstream registry at revision {revision}",
    )
    workstream = _find_workstream(registry, workstream_id)
    registered_paths = _string_list(workstream, "owned_paths")
    if not registered_paths:
        raise click.ClickException(f"Workstream has no writable paths: {workstream_id}")
    _validate_registered_paths(repository_root, registered_paths)
    writable_paths = [] if normalized_mode in READ_ONLY_MODES else registered_paths
    prohibited_effects = _prohibited_effects(normalized_mode)
    context_paths = _context_paths(
        repository_root=repository_root,
        workstream=workstream,
        writable_paths=registered_paths,
    )
    assignment = _assignment(
        slug=slug,
        workstream_id=workstream_id,
        mode=normalized_mode,
        learning_level=normalized_learning_level,
        revision=revision,
        branch=branch,
        repository_root=repository_root,
        objective=normalized_objective,
        context_paths=context_paths,
        writable_paths=writable_paths,
        prohibited_effects=prohibited_effects,
    )
    try:
        validate_agent_assignment(
            assignment=assignment,
            registry=registry,
            repository_root=repository_root,
            expected_branch=branch,
            expected_revision=revision,
        )
    except AssignmentValidationError as error:
        raise click.ClickException(f"Invalid coding assignment: {error}") from error

    coding_run: dict[str, object] = {
        "schema_version": 1,
        "run_id": f"coding-{slug}",
        "name": normalized_name,
        "status": "active",
        "created_at": created_at.isoformat(),
        "objective": normalized_objective,
        "persistence_reason": normalized_persistence_reason,
        "classification": normalized_classification,
        "review_on": review_on.isoformat(),
        "jira": {
            "key": normalized_jira_key,
            "title": None,
            "url": None,
            "evidence_status": "pending-verification",
        },
        "repository": {
            "path": str(repository_root),
            "branch": branch,
            "revision": revision,
            "working_tree": "clean",
        },
        "workstream": workstream_id,
        "active_mode": normalized_mode,
        "mode_history": [
            {
                "mode": normalized_mode,
                "entered_at": created_at.isoformat(),
                "reason": "Owner-selected initial mode.",
                "revision": revision,
            }
        ],
        "learning_level": normalized_learning_level,
        "context_manifest": _context_manifest(
            repository_root=repository_root,
            revision=revision,
            context_paths=context_paths,
            loaded_at=created_at,
        ),
        "writable_paths": writable_paths,
        "required_checks": list(REQUIRED_CHECKS),
        "prohibited_effects": prohibited_effects,
        "completion_criteria": list(COMPLETION_CRITERIA),
        "gates": {
            "design": "required",
            "tdd": "pending",
            "verification": "pending",
            "review": "pending",
            "pr_draft": "pending",
        },
        "evidence": {
            "design_records": [],
            "tdd_cycles": [],
            "verification_runs": [],
            "review_runs": [],
            "closeouts": [],
            "pr_drafts": [],
        },
        "assignment": {
            "status": "not-launched",
            "path": "agent-assignment.preview.json",
        },
    }
    run_relative_path = CODING_RUN_DIRECTORY / slug / "coding-run.json"
    assignment_relative_path = (
        CODING_RUN_DIRECTORY / slug / "agent-assignment.preview.json"
    )
    _require_unchanged_repository(
        repository_root=repository_root,
        branch=branch,
        revision=revision,
    )
    with _coding_run_lock(audit_root):
        _require_unchanged_repository(
            repository_root=repository_root,
            branch=branch,
            revision=revision,
        )
        run_directory = vault_root / run_relative_path.parent
        if review_on < created_at.astimezone().date() and not run_directory.exists():
            raise click.ClickException(
                f"Review date must be today or later: {review_on.isoformat()}"
            )
        created = _write_run_directory(
            vault_root=vault_root,
            run_relative_path=run_relative_path,
            coding_run=coding_run,
            assignment=assignment,
        )
        try:
            _require_unchanged_repository(
                repository_root=repository_root,
                branch=branch,
                revision=revision,
            )
        except click.ClickException:
            if created:
                _remove_created_run(
                    vault_root=vault_root,
                    run_relative_path=run_relative_path,
                    coding_run=coding_run,
                    assignment=assignment,
                )
            raise
    return CodingRunResult(
        slug=slug,
        run_path=run_relative_path,
        assignment_path=assignment_relative_path,
        created=created,
    )


def _assignment(
    *,
    slug: str,
    workstream_id: str,
    mode: str,
    learning_level: str,
    revision: str,
    branch: str,
    repository_root: Path,
    objective: str,
    context_paths: list[str],
    writable_paths: list[str],
    prohibited_effects: list[str],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "assignment_kind": "active",
        "assignment_id": f"coding-{slug}",
        "workstream": workstream_id,
        "mode": mode,
        "learning_level": learning_level,
        "base_revision": revision,
        "branch": branch,
        "worktree": str(repository_root),
        "objective": objective,
        "context_paths": context_paths,
        "writable_paths": writable_paths,
        "required_checks": list(REQUIRED_CHECKS),
        "prohibited_effects": prohibited_effects,
        "completion_criteria": list(COMPLETION_CRITERIA),
    }


def _prohibited_effects(mode: str) -> list[str]:
    effects: list[str] = list(BASE_PROHIBITED_EFFECTS)
    if mode in READ_ONLY_MODES:
        effects.append("Do not modify the target repository.")
    else:
        effects.append("Do not modify paths outside the declared writable paths.")
    return effects


def _context_manifest(
    *,
    repository_root: Path,
    revision: str,
    context_paths: list[str],
    loaded_at: datetime,
) -> list[dict[str, str]]:
    manifest: list[dict[str, str]] = []
    for path in context_paths:
        try:
            content = _git_bytes(repository_root, "show", f"{revision}:{path}")
        except subprocess.CalledProcessError as error:
            raise click.ClickException(
                f"Repository context is unavailable at revision {revision}: {path}"
            ) from error
        manifest.append(
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "loaded_at": loaded_at.isoformat(),
            }
        )
    return manifest


def _context_paths(
    *,
    repository_root: Path,
    workstream: dict[str, object],
    writable_paths: list[str],
) -> list[str]:
    required = {
        "AGENTS.md",
        "docs/agent-context.md",
        "docs/engineering/owner-practices.md",
        _require_string(workstream, "context"),
    }
    context_paths = set(required)
    context_paths.update(governing_instruction_paths(repository_root, writable_paths))
    ordered_paths = sorted(context_paths)
    for path in ordered_paths:
        _require_contained_path(
            repository_root,
            path,
            "Repository context resolves outside repository",
        )
        if not (repository_root / path).is_file():
            raise click.ClickException(
                f"Required repository context is missing: {path}"
            )
    return ordered_paths


def _find_workstream(
    registry: dict[str, object],
    workstream_id: str,
) -> dict[str, object]:
    workstreams = registry.get("workstreams")
    if not isinstance(workstreams, list):
        raise click.ClickException("Workstream registry has invalid workstreams.")
    for value in cast(list[object], workstreams):
        if isinstance(value, dict):
            workstream = cast(dict[str, object], value)
            if workstream.get("id") == workstream_id:
                return workstream
    raise click.ClickException(f"Unknown workstream: {workstream_id}")


def _normalize_text(value: str, label: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise click.ClickException(f"{label} must not be empty.")
    return normalized


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if not slug:
        raise click.ClickException("Coding run name must contain letters or numbers.")
    return slug


def _validate_jira_key(value: str) -> str:
    normalized = value.strip().upper()
    if not JIRA_KEY_PATTERN.fullmatch(normalized):
        raise click.ClickException(f"Invalid JIRA key: {value}")
    return normalized


def _validate_choice(value: str, label: str, allowed: set[str] | frozenset[str]) -> str:
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise click.ClickException(f"Invalid {label}: {value}")
    return normalized


def _validate_repository(repository: Path) -> Path:
    if not repository.is_absolute():
        raise click.ClickException("Repository path must be absolute.")
    resolved = repository.expanduser().resolve()
    if not resolved.is_dir():
        raise click.ClickException(f"Repository does not exist: {repository}")
    try:
        top_level = Path(_git_value(resolved, "rev-parse", "--show-toplevel")).resolve()
    except subprocess.CalledProcessError as error:
        raise click.ClickException(
            f"Path is not a Git repository: {repository}"
        ) from error
    if top_level != resolved:
        raise click.ClickException(
            f"Repository path must be the Git root: {repository}"
        )
    return resolved


def _git_value(repository_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_bytes(repository_root: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return result.stdout


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


def _require_unchanged_repository(
    *,
    repository_root: Path,
    branch: str,
    revision: str,
) -> None:
    current_branch, current_revision, working_tree_clean = _repository_state(
        repository_root
    )
    if (
        current_branch != branch
        or current_revision != revision
        or not working_tree_clean
    ):
        raise click.ClickException("Repository changed while preparing coding run.")


def _load_mapping(path: Path, label: str) -> dict[str, object]:
    try:
        return _load_mapping_bytes(path.read_bytes(), label)
    except OSError as error:
        raise click.ClickException(f"Cannot read {label}: {path}") from error


def _load_mapping_bytes(content: bytes, label: str) -> dict[str, object]:
    try:
        value: object = json.loads(content)
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {label}.") from error
    if not isinstance(value, dict):
        raise click.ClickException(f"{label.capitalize()} must be a JSON object.")
    return cast(dict[str, object], value)


def _require_string(mapping: dict[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise click.ClickException(f"Workstream field must be text: {field}")
    return value


def _string_list(mapping: dict[str, object], field: str) -> list[str]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise click.ClickException(f"Workstream field must be a list: {field}")
    items = cast(list[object], value)
    if any(not isinstance(item, str) or not item.strip() for item in items):
        raise click.ClickException(f"Workstream list must contain text: {field}")
    return cast(list[str], items)


def _validate_registered_paths(repository_root: Path, paths: list[str]) -> None:
    for value in paths:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise click.ClickException(f"Unsafe registered writable path: {value}")
        _require_contained_path(
            repository_root,
            value,
            "Registered writable path resolves outside repository",
        )


def _require_contained_path(
    repository_root: Path,
    value: str,
    message: str,
) -> None:
    resolved = (repository_root / value).resolve()
    try:
        resolved.relative_to(repository_root)
    except ValueError as error:
        raise click.ClickException(f"{message}: {value}") from error


def _write_run_directory(
    *,
    vault_root: Path,
    run_relative_path: Path,
    coding_run: dict[str, object],
    assignment: dict[str, object],
) -> bool:
    run_directory = vault_root / run_relative_path.parent
    run_root = run_directory.parent
    run_root.mkdir(parents=True, exist_ok=True)
    if run_directory.exists():
        if _existing_run_matches(run_directory, coding_run, assignment):
            return False
        raise click.ClickException(
            "Coding run name identifies a run with different inputs: "
            f"{run_directory.name}"
        )

    temporary_directory = Path(
        tempfile.mkdtemp(prefix=f".{run_directory.name}.", dir=run_root)
    )
    try:
        _write_json(temporary_directory / "coding-run.json", coding_run)
        _write_json(
            temporary_directory / "agent-assignment.preview.json",
            assignment,
        )
        os.rename(temporary_directory, run_directory)
        return True
    except FileExistsError as error:
        raise click.ClickException(
            f"Coding run already exists: {run_directory.name}"
        ) from error
    except OSError as error:
        raise click.ClickException(f"Cannot create coding run: {error}") from error
    finally:
        shutil.rmtree(temporary_directory, ignore_errors=True)


def _existing_run_matches(
    run_directory: Path,
    coding_run: dict[str, object],
    assignment: dict[str, object],
) -> bool:
    try:
        existing_run = _load_mapping(run_directory / "coding-run.json", "coding run")
        existing_assignment = _load_mapping(
            run_directory / "agent-assignment.preview.json",
            "agent assignment",
        )
    except click.ClickException:
        return False
    return (
        _stable_run_identity(existing_run) == _stable_run_identity(coding_run)
        and existing_assignment == assignment
    )


def _remove_created_run(
    *,
    vault_root: Path,
    run_relative_path: Path,
    coding_run: dict[str, object],
    assignment: dict[str, object],
) -> None:
    run_directory = vault_root / run_relative_path.parent
    try:
        entries = {entry.name for entry in run_directory.iterdir()}
    except OSError:
        return
    if entries != {"coding-run.json", "agent-assignment.preview.json"}:
        return
    try:
        existing_run = _load_mapping(run_directory / "coding-run.json", "coding run")
        existing_assignment = _load_mapping(
            run_directory / "agent-assignment.preview.json",
            "agent assignment",
        )
    except click.ClickException:
        return
    if existing_run != coding_run or existing_assignment != assignment:
        return
    shutil.rmtree(run_directory)


def _stable_run_identity(coding_run: dict[str, object]) -> dict[str, object]:
    identity = {
        key: value
        for key, value in coding_run.items()
        if key not in {"created_at", "mode_history", "context_manifest"}
    }
    identity["mode_history"] = _records_without_field(
        coding_run.get("mode_history"),
        "entered_at",
    )
    identity["context_manifest"] = _records_without_field(
        coding_run.get("context_manifest"),
        "loaded_at",
    )
    return identity


def _records_without_field(value: object, omitted_field: str) -> list[object]:
    if not isinstance(value, list):
        return []
    records: list[object] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            records.append(item)
            continue
        record = cast(dict[object, object], item)
        records.append(
            {
                key: field_value
                for key, field_value in record.items()
                if key != omitted_field
            }
        )
    return records


def _write_json(path: Path, value: dict[str, object]) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as destination:
        destination.write(content)
        destination.flush()
        os.fsync(destination.fileno())


def _now() -> datetime:
    return datetime.now().astimezone()


@contextmanager
def _coding_run_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / "code-start.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
