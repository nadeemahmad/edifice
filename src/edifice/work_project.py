"""Maintain scoped projects and the selected project pointer."""

import fcntl
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import cast

import click

from edifice.identifiers import new_uuid7

CURRENT_POINTER = Path("00-system/current.json")
PROJECT_STATUSES = frozenset({"active", "on-hold", "completed"})
PROJECT_SCOPES = frozenset({"personal", "work"})
WORK_CLASSIFICATIONS = frozenset({"public", "netflix-internal", "netflix-confidential"})


@dataclass(frozen=True)
class WorkProjectResult:
    project_id: str
    slug: str
    note_path: Path
    scope: str


@dataclass(frozen=True)
class WorkProjectItem:
    project_id: str
    slug: str
    title: str
    status: str
    note_path: Path
    scope: str
    selected: bool


def project_directory(scope: str) -> Path:
    normalized = _scope(scope)
    root = "10-personal" if normalized == "personal" else "20-work"
    return Path(root) / "operations" / "projects"


def project_index(scope: str) -> Path:
    return project_directory(scope) / "index.json"


def start_work_project(
    *,
    vault_root: Path,
    audit_root: Path,
    name: str,
    classification: str | None,
    review_on: date,
    persistence_reason: str,
    scope: str = "work",
    created_on: date | None = None,
) -> WorkProjectResult:
    normalized_scope = _scope(scope)
    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise click.ClickException("Project name must not be empty.")
    slug = _slug(normalized_name)
    normalized_classification = _classification(
        normalized_scope,
        classification,
    )
    reason = persistence_reason.strip()
    if not reason:
        raise click.ClickException("Persistence reason must not be empty.")
    effective_created = created_on or _today()
    if review_on < effective_created:
        raise click.ClickException(
            f"Review date must be today or later: {review_on.isoformat()}"
        )
    project_id = f"project-{new_uuid7()}"
    relative_note = project_directory(normalized_scope) / f"{slug}.md"
    note_path = vault_root / relative_note
    index_path = vault_root / project_index(normalized_scope)
    current_path = vault_root / CURRENT_POINTER
    now = _now()
    note = _render_note(
        project_id,
        normalized_name,
        normalized_scope,
        normalized_classification,
        effective_created,
        review_on,
        reason,
    ).encode()
    with _project_lock(audit_root):
        current = _load_json_object(current_path, "current-state pointer")
        index = _load_index(index_path, now)
        projects = cast(dict[str, object], index["projects"])
        if note_path.exists() or any(
            isinstance(value, dict)
            and cast(dict[str, object], value).get("slug") == slug
            for value in projects.values()
        ):
            raise click.ClickException(f"Work project already exists: {slug}")
        projects[project_id] = {
            "project_id": project_id,
            "slug": slug,
            "title": normalized_name,
            "scope": normalized_scope,
            "status": "active",
            "classification": normalized_classification,
            "note_path": relative_note.as_posix(),
            "created_at": now.isoformat(),
            "review_on": review_on.isoformat(),
            "persistence_reason": reason,
        }
        index["updated_at"] = now.isoformat()
        current["work"] = relative_note.as_posix()
        current[f"{normalized_scope}_project"] = relative_note.as_posix()
        previous_index = index_path.read_bytes() if index_path.exists() else None
        previous_current = current_path.read_bytes()
        _write_new(note_path, note)
        try:
            _replace(index_path, _encoded(index))
            _replace(current_path, _encoded(current))
        except Exception:
            try:
                _restore(index_path, previous_index)
            finally:
                try:
                    _replace(current_path, previous_current)
                finally:
                    if note_path.read_bytes() == note:
                        note_path.unlink()
            raise
        _audit(audit_root, "project.started", project_id, normalized_scope)
    return WorkProjectResult(project_id, slug, relative_note, normalized_scope)


def list_work_projects(
    *,
    vault_root: Path,
    scope: str | None = None,
) -> tuple[WorkProjectItem, ...]:
    scopes = (_scope(scope),) if scope else ("personal", "work")
    current = _load_json_object(vault_root / CURRENT_POINTER, "current-state pointer")
    items: list[WorkProjectItem] = []
    for candidate_scope in scopes:
        index_path = vault_root / project_index(candidate_scope)
        index = _load_index(index_path, _now())
        for project_id, value in cast(dict[str, object], index["projects"]).items():
            record = _record(value, index_path, candidate_scope)
            note_path = Path(cast(str, record["note_path"]))
            items.append(
                WorkProjectItem(
                    project_id,
                    cast(str, record["slug"]),
                    cast(str, record["title"]),
                    cast(str, record["status"]),
                    note_path,
                    candidate_scope,
                    current.get("work") == note_path.as_posix(),
                )
            )
    return tuple(sorted(items, key=lambda item: (item.scope, item.title.casefold())))


def get_work_project(
    *,
    vault_root: Path,
    project: str,
    scope: str | None = None,
) -> WorkProjectItem:
    matches = [
        item
        for item in list_work_projects(vault_root=vault_root, scope=scope)
        if item.project_id == project.strip() or item.slug == project.strip()
    ]
    if len(matches) != 1:
        raise click.ClickException(
            f"Work project does not exist or is ambiguous: {project}"
        )
    return matches[0]


def get_current_project(*, vault_root: Path) -> WorkProjectItem | None:
    current = _load_json_object(vault_root / CURRENT_POINTER, "current-state pointer")
    selected = current.get("work")
    if not isinstance(selected, str):
        return None
    matches = [
        item
        for item in list_work_projects(vault_root=vault_root)
        if item.note_path.as_posix() == selected
    ]
    return matches[0] if len(matches) == 1 else None


def select_work_project(
    *,
    vault_root: Path,
    audit_root: Path,
    project: str,
    scope: str | None = None,
) -> WorkProjectItem:
    item = get_work_project(vault_root=vault_root, project=project, scope=scope)
    if item.status == "completed":
        raise click.ClickException("Cannot select a completed project.")
    with _project_lock(audit_root):
        current_path = vault_root / CURRENT_POINTER
        current = _load_json_object(current_path, "current-state pointer")
        current["work"] = item.note_path.as_posix()
        current[f"{item.scope}_project"] = item.note_path.as_posix()
        _replace(current_path, _encoded(current))
        _audit(audit_root, "project.selected", item.project_id, item.scope)
    return get_work_project(vault_root=vault_root, project=item.project_id)


def mark_work_project(
    *,
    vault_root: Path,
    audit_root: Path,
    project: str,
    status: str,
    scope: str | None = None,
) -> WorkProjectItem:
    normalized = status.strip().lower()
    if normalized not in PROJECT_STATUSES:
        raise click.ClickException(f"Invalid project status: {status}")
    item = get_work_project(vault_root=vault_root, project=project, scope=scope)
    index_path = vault_root / project_index(item.scope)
    note_path = vault_root / item.note_path
    with _project_lock(audit_root):
        index = _load_index(index_path, _now())
        record = cast(
            dict[str, object],
            cast(dict[str, object], index["projects"])[item.project_id],
        )
        old = f"status: {record['status']}"
        note = note_path.read_text()
        if note.count(old) != 1:
            raise click.ClickException("Project note status is invalid.")
        record["status"] = normalized
        index["updated_at"] = _now().isoformat()
        previous = note.encode()
        _replace(note_path, note.replace(old, f"status: {normalized}", 1).encode())
        try:
            _replace(index_path, _encoded(index))
        except Exception:
            _replace(note_path, previous)
            raise
        _audit(audit_root, "project.marked", item.project_id, item.scope)
    return get_work_project(vault_root=vault_root, project=item.project_id)


def _scope(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in PROJECT_SCOPES:
        raise click.ClickException(f"Invalid project scope: {value}")
    return normalized


def _classification(scope: str, value: str | None) -> str:
    if scope == "personal":
        if value not in {None, "personal"}:
            raise click.ClickException("Personal projects use personal classification.")
        return "personal"
    normalized = (value or "").strip().lower()
    if normalized not in WORK_CLASSIFICATIONS:
        raise click.ClickException("Work projects require --classification.")
    return normalized


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if not slug:
        raise click.ClickException("Project name must contain letters or numbers.")
    return slug


def _render_note(
    project_id: str,
    title: str,
    scope: str,
    classification: str,
    created: date,
    review_on: date,
    reason: str,
) -> str:
    return f"""---
id: {project_id}
type: project
schema_version: 1
created: {created.isoformat()}
status: active
health: on-track
title: {json.dumps(title)}
scope: {scope}
classification: {json.dumps(classification)}
primary_anchor: local-project
context_status: unavailable
authoritative_source: not-applicable
jira: not-applicable
repository: not-applicable
review_on: {review_on.isoformat()}
persistence_reason: {json.dumps(reason)}
---

# {title}

## Result

## Current state

- Context: `unavailable`
- JIRA: `not-applicable`
- Repository: `not-applicable`

## Manual context

### Notes

### Links

### PDFs

### Decisions

### Questions

## Resume point

## Tasks

## Completion

Owner approval is required before marking this project complete.
"""


def _load_index(path: Path, now: datetime) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "updated_at": now.isoformat(), "projects": {}}
    value = _load_json_object(path, "project index")
    if (
        set(value) != {"schema_version", "updated_at", "projects"}
        or value.get("schema_version") != 1
        or not isinstance(value.get("projects"), dict)
    ):
        raise click.ClickException(f"Invalid project index: {path}")
    for item in cast(dict[str, object], value["projects"]).values():
        _record(item, path, "personal" if "10-personal" in path.parts else "work")
    return value


def _record(value: object, path: Path, scope: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid project index: {path}")
    record = cast(dict[str, object], value)
    required = {
        "project_id",
        "slug",
        "title",
        "scope",
        "status",
        "classification",
        "note_path",
        "created_at",
        "review_on",
        "persistence_reason",
    }
    if set(record) != required or any(
        not isinstance(record.get(key), str) for key in required
    ):
        raise click.ClickException(f"Invalid project index: {path}")
    note = PurePosixPath(cast(str, record["note_path"]))
    root = PurePosixPath(project_directory(scope).as_posix())
    if (
        record["scope"] != scope
        or note.parts[: len(root.parts)] != root.parts
        or note.suffix != ".md"
        or ".." in note.parts
    ):
        raise click.ClickException(f"Invalid project index: {path}")
    return record


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {label}: {path}") from error
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid {label}: {path}")
    return cast(dict[str, object], value)


def _today() -> date:
    return datetime.now().astimezone().date()


def _now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def _project_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(audit_root / "projects.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.link(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _replace(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        if path.exists():
            temporary_path.chmod(path.stat().st_mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _restore(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        _replace(path, previous)


def _encoded(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _audit(audit_root: Path, event_type: str, project_id: str, scope: str) -> None:
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": _now().isoformat(),
        "profile": scope,
        "event_type": event_type,
        "project_id": project_id,
        "external_mutation": False,
    }
    path = audit_root / f"{_now().date().isoformat()}.jsonl"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(event, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
