"""Maintain scoped tasks with optional project assignment."""

import fcntl
import json
import os
import re
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import click

from edifice.identifiers import new_uuid7
from edifice.work_project import (
    WorkProjectItem,
    get_current_project,
    get_work_project,
    list_work_projects,
    start_work_project,
)

TASK_SCOPES = frozenset({"personal", "work"})


@dataclass(frozen=True)
class WorkTaskResult:
    slug: str
    note_path: Path


@dataclass(frozen=True)
class ProjectTaskItem:
    task_id: str
    project_id: str | None
    project_slug: str | None
    scope: str
    text: str
    status: str


def task_index(scope: str) -> Path:
    root = "10-personal" if _scope(scope) == "personal" else "20-work"
    return Path(root) / "operations" / "tasks" / "index.json"


def task_inbox(scope: str) -> Path:
    return task_index(scope).with_name("inbox.md")


def start_work_task(
    *,
    vault_root: Path,
    audit_root: Path,
    name: str,
    classification: str,
    review_on: date,
    persistence_reason: str,
) -> WorkTaskResult:
    try:
        project = start_work_project(
            vault_root=vault_root,
            audit_root=audit_root,
            name=name,
            classification=classification,
            review_on=review_on,
            persistence_reason=persistence_reason,
            created_on=_today(),
        )
    except click.ClickException as error:
        message = error.format_message().replace("Work project", "Work task")
        message = message.replace("Project name", "Task name")
        raise click.ClickException(message) from error
    return WorkTaskResult(project.slug, project.note_path)


def add_project_task(
    *,
    vault_root: Path,
    audit_root: Path,
    text: str,
    project: str | None = None,
    scope: str | None = None,
    no_project: bool = False,
) -> ProjectTaskItem:
    normalized = " ".join(text.split())
    if not normalized:
        raise click.ClickException("Task text must not be empty.")
    if project and no_project:
        raise click.ClickException("Use either --project or --no-project.")
    assignment_reason: str | None = None
    project_item: WorkProjectItem | None = None
    if project:
        project_item = get_work_project(
            vault_root=vault_root, project=project, scope=scope
        )
        assignment_reason = "explicit"
    elif not no_project:
        project_item = get_current_project(vault_root=vault_root)
        if project_item:
            assignment_reason = "current-project"
    effective_scope = project_item.scope if project_item else _scope(scope)
    if project_item and project_item.status == "completed":
        raise click.ClickException("Cannot add a task to a completed project.")
    now = _now()
    task_id = f"task-{new_uuid7()}"
    index_path = vault_root / task_index(effective_scope)
    with _task_lock(audit_root):
        index = _load_index(index_path, now)
        record: dict[str, object] = {
            "task_id": task_id,
            "scope": effective_scope,
            "project_id": project_item.project_id if project_item else None,
            "text": normalized,
            "status": "open",
            "created_at": now.isoformat(),
            "completed_at": None,
            "assignment_history": [],
        }
        if project_item:
            cast(list[object], record["assignment_history"]).append(
                _assignment(
                    None, project_item.project_id, assignment_reason or "explicit", now
                )
            )
        cast(dict[str, object], index["tasks"])[task_id] = record
        index["updated_at"] = now.isoformat()
        _persist_assignment(
            vault_root=vault_root,
            scope=effective_scope,
            index=index,
            old_project=None,
            new_project=project_item,
            task_id=task_id,
            text=normalized,
            checked=False,
        )
        _audit(audit_root, "task.added", task_id, effective_scope, project_item)
    return _item(record, project_item)


def assign_project_task(
    *,
    vault_root: Path,
    audit_root: Path,
    task_id: str,
    project: str | None,
    reason: str,
) -> ProjectTaskItem:
    scope, index, record = _find_task(vault_root, task_id)
    old_id = cast(str | None, record["project_id"])
    old_project = (
        get_work_project(vault_root=vault_root, project=old_id) if old_id else None
    )
    new_project = (
        get_work_project(vault_root=vault_root, project=project) if project else None
    )
    if new_project and new_project.scope != scope:
        raise click.ClickException("Task and project scopes must match.")
    if new_project and new_project.status == "completed":
        raise click.ClickException("Cannot assign a task to a completed project.")
    now = _now()
    record["project_id"] = new_project.project_id if new_project else None
    cast(list[object], record["assignment_history"]).append(
        _assignment(
            old_id, new_project.project_id if new_project else None, reason, now
        )
    )
    index["updated_at"] = now.isoformat()
    with _task_lock(audit_root):
        _persist_assignment(
            vault_root=vault_root,
            scope=scope,
            index=index,
            old_project=old_project,
            new_project=new_project,
            task_id=task_id,
            text=cast(str, record["text"]),
            checked=record["status"] == "completed",
        )
        _audit(audit_root, "task.assigned", task_id, scope, new_project)
    return _item(record, new_project)


def list_project_tasks(
    *,
    vault_root: Path,
    project: str,
) -> tuple[ProjectTaskItem, ...]:
    project_item = get_work_project(vault_root=vault_root, project=project)
    index = _load_index(vault_root / task_index(project_item.scope), _now())
    items: list[ProjectTaskItem] = []
    for value in cast(dict[str, object], index["tasks"]).values():
        if not isinstance(value, dict):
            continue
        record = cast(dict[str, object], value)
        if record.get("project_id") == project_item.project_id:
            items.append(_item(record, project_item))
    return tuple(items)


def complete_project_task(
    *,
    vault_root: Path,
    audit_root: Path,
    task_id: str,
) -> str:
    scope, index, record = _find_task(vault_root, task_id)
    project_id = cast(str | None, record["project_id"])
    project = (
        get_work_project(vault_root=vault_root, project=project_id)
        if project_id
        else None
    )
    record["status"] = "completed"
    record["completed_at"] = _now().isoformat()
    index["updated_at"] = _now().isoformat()
    with _task_lock(audit_root):
        _persist_assignment(
            vault_root=vault_root,
            scope=scope,
            index=index,
            old_project=project,
            new_project=project,
            task_id=task_id,
            text=cast(str, record["text"]),
            checked=True,
        )
        _audit(audit_root, "task.completed", task_id, scope, project)
    return task_id


def auto_assign_task(
    *,
    vault_root: Path,
    audit_root: Path,
    task_id: str,
    apply: bool,
) -> tuple[ProjectTaskItem | None, tuple[str, ...]]:
    scope, _, record = _find_task(vault_root, task_id)
    if record["project_id"] is not None:
        raise click.ClickException("Task is already assigned.")
    words = _terms(cast(str, record["text"]))
    candidates: list[tuple[WorkProjectItem, tuple[str, ...]]] = []
    for project in list_work_projects(vault_root=vault_root, scope=scope):
        if project.status == "completed":
            continue
        overlap = tuple(sorted(words & _terms(project.title)))
        if overlap:
            candidates.append((project, overlap))
    candidates.sort(key=lambda candidate: len(candidate[1]), reverse=True)
    if not candidates or (
        len(candidates) > 1 and len(candidates[0][1]) == len(candidates[1][1])
    ):
        return None, ()
    project, overlap = candidates[0]
    if apply:
        return (
            assign_project_task(
                vault_root=vault_root,
                audit_root=audit_root,
                task_id=task_id,
                project=project.project_id,
                reason="auto-assigned",
            ),
            overlap,
        )
    return _item(record, project), overlap


def _persist_assignment(
    *,
    vault_root: Path,
    scope: str,
    index: dict[str, object],
    old_project: WorkProjectItem | None,
    new_project: WorkProjectItem | None,
    task_id: str,
    text: str,
    checked: bool,
) -> None:
    paths: dict[Path, bytes] = {}
    if old_project:
        old_path = vault_root / old_project.note_path
        paths[old_path] = _remove_task(old_path.read_text(), task_id).encode()
    if new_project:
        new_path = vault_root / new_project.note_path
        base = paths.get(new_path, new_path.read_bytes()).decode()
        paths[new_path] = _append_task(base, task_id, text, checked).encode()
    index_path = vault_root / task_index(scope)
    paths[index_path] = _encoded(index)
    paths[vault_root / task_inbox(scope)] = _render_inbox(index, scope).encode()
    previous = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        for path, content in paths.items():
            _replace(path, content)
    except Exception:
        for path, content in previous.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                _replace(path, content)
        raise


def _append_task(note: str, task_id: str, text: str, checked: bool) -> str:
    note = _remove_task(note, task_id)
    lines = note.splitlines()
    heading = lines.index("## Tasks")
    insertion = heading + 1
    while insertion < len(lines) and not lines[insertion].startswith("## "):
        insertion += 1
    mark = "x" if checked else " "
    lines.insert(insertion, f"- [{mark}] {text} ^{task_id}")
    return "\n".join(lines).rstrip() + "\n"


def _remove_task(note: str, task_id: str) -> str:
    lines = [line for line in note.splitlines() if not line.endswith(f" ^{task_id}")]
    return "\n".join(lines).rstrip() + "\n"


def _render_inbox(index: dict[str, object], scope: str) -> str:
    lines = [f"# {scope.title()} unassigned tasks", ""]
    for task_id, value in cast(dict[str, object], index["tasks"]).items():
        if not isinstance(value, dict):
            continue
        record = cast(dict[str, object], value)
        if record.get("project_id") is None:
            mark = "x" if record.get("status") == "completed" else " "
            lines.append(f"- [{mark}] {record.get('text')} ^{task_id}")
    if len(lines) == 2:
        lines.append("No unassigned tasks.")
    return "\n".join(lines) + "\n"


def _find_task(
    vault_root: Path,
    task_id: str,
) -> tuple[str, dict[str, object], dict[str, object]]:
    for scope in ("personal", "work"):
        index = _load_index(vault_root / task_index(scope), _now())
        value = cast(dict[str, object], index["tasks"]).get(task_id)
        if isinstance(value, dict):
            return scope, index, cast(dict[str, object], value)
    raise click.ClickException(f"Task does not exist: {task_id}")


def _load_index(path: Path, now: datetime) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "updated_at": now.isoformat(), "tasks": {}}
    try:
        value: object = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read task index: {path}") from error
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid task index: {path}")
    typed_value = cast(dict[str, object], value)
    if not isinstance(typed_value.get("tasks"), dict):
        raise click.ClickException(f"Invalid task index: {path}")
    return typed_value


def _item(
    record: dict[str, object], project: WorkProjectItem | None
) -> ProjectTaskItem:
    return ProjectTaskItem(
        cast(str, record["task_id"]),
        cast(str | None, record["project_id"]),
        project.slug if project else None,
        cast(str, record["scope"]),
        cast(str, record["text"]),
        cast(str, record["status"]),
    )


def _assignment(
    previous: str | None,
    current: str | None,
    reason: str,
    now: datetime,
) -> dict[str, object]:
    return {
        "previous_project_id": previous,
        "project_id": current,
        "reason": reason,
        "changed_at": now.isoformat(),
    }


def _terms(value: str) -> set[str]:
    return {
        term for term in re.findall(r"[a-z0-9]+", value.casefold()) if len(term) >= 3
    }


def _scope(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in TASK_SCOPES:
        raise click.ClickException("Unassigned tasks require --scope personal or work.")
    return normalized


def _today() -> date:
    return datetime.now().astimezone().date()


def _now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def _task_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(audit_root / "tasks.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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


def _encoded(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _audit(
    audit_root: Path,
    event_type: str,
    task_id: str,
    scope: str,
    project: WorkProjectItem | None,
) -> None:
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": _now().isoformat(),
        "profile": scope,
        "event_type": event_type,
        "task_id": task_id,
        "project_id": project.project_id if project else None,
        "external_mutation": False,
    }
    path = audit_root / f"{_now().date().isoformat()}.jsonl"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(event, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
