"""Create local work tasks that begin without gathered context."""

import fcntl
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

import click

from edifice.identifiers import new_uuid7

TASK_DIRECTORY = Path("20-work/operations/projects")
CURRENT_POINTER = Path("00-system/current.json")
MAX_SLUG_LENGTH = 120
CLASSIFICATIONS = frozenset({"public", "netflix-internal", "netflix-confidential"})


@dataclass(frozen=True)
class WorkTaskResult:
    slug: str
    note_path: Path


def start_work_task(
    *,
    vault_root: Path,
    audit_root: Path,
    name: str,
    classification: str,
    review_on: date,
    persistence_reason: str,
) -> WorkTaskResult:
    """Create and select one work task without gathering external context."""
    normalized_name = _normalize_name(name)
    slug = _slug(normalized_name)
    normalized_classification = classification.strip().lower()
    if normalized_classification not in CLASSIFICATIONS:
        raise click.ClickException(f"Invalid work classification: {classification}")
    normalized_persistence_reason = persistence_reason.strip()
    if not normalized_persistence_reason:
        raise click.ClickException("Persistence reason must not be empty.")
    created_on = _today()
    if review_on < created_on:
        raise click.ClickException(
            f"Review date must be today or later: {review_on.isoformat()}"
        )

    note_relative_path = TASK_DIRECTORY / f"{slug}.md"
    note_path = vault_root / note_relative_path
    current_path = vault_root / CURRENT_POINTER
    note = _render_task_note(
        name=normalized_name,
        classification=normalized_classification,
        created_on=created_on,
        review_on=review_on,
        persistence_reason=normalized_persistence_reason,
    ).encode()

    with _task_lock(audit_root):
        current = _load_current_pointer(current_path)
        if note_path.exists():
            raise click.ClickException(f"Work task already exists: {slug}")

        updated_current = dict(current)
        updated_current["work"] = note_relative_path.as_posix()
        encoded_current = (
            json.dumps(updated_current, indent=2, sort_keys=True) + "\n"
        ).encode()

        _write_new_atomically(note_path, note)
        try:
            _replace_atomically(current_path, encoded_current)
        except Exception:
            _remove_unchanged_file(note_path, note)
            raise

    return WorkTaskResult(slug=slug, note_path=note_relative_path)


def _normalize_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise click.ClickException("Task name must not be empty.")
    return normalized


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if not slug:
        raise click.ClickException("Task name must contain letters or numbers.")
    if len(slug) > MAX_SLUG_LENGTH:
        raise click.ClickException(
            f"Task name produces a filename longer than {MAX_SLUG_LENGTH} characters."
        )
    return slug


def _load_current_pointer(path: Path) -> dict[str, object]:
    try:
        current: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {path}") from error
    if not isinstance(current, dict):
        raise click.ClickException("Current-state pointer must be a JSON object.")
    return cast(dict[str, object], current)


def _render_task_note(
    *,
    name: str,
    classification: str,
    created_on: date,
    review_on: date,
    persistence_reason: str,
) -> str:
    return f"""---
id: project_{new_uuid7()}
type: project
schema_version: 1
created: {created_on.isoformat()}
status: active
health: on-track
title: {json.dumps(name)}
classification: {json.dumps(classification)}
context_status: unavailable
authoritative_source: not-applicable
jira: not-applicable
repository: not-applicable
review_on: {review_on.isoformat()}
persistence_reason: {json.dumps(persistence_reason)}
---

# {name}

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

- [ ] Define the result and first concrete action.

## Completion

Owner approval is required before marking this task complete.
"""


def _today() -> date:
    return datetime.now().astimezone().date()


@contextmanager
def _task_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / "task-start.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_new_atomically(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)

    try:
        os.link(temporary_path, target)
    except FileExistsError as error:
        raise click.ClickException(
            f"Work task already exists: {target.stem}"
        ) from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _replace_atomically(target: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)

    try:
        temporary_path.chmod(target.stat().st_mode)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def _remove_unchanged_file(path: Path, expected: bytes) -> None:
    try:
        if path.read_bytes() == expected:
            path.unlink()
    except OSError:
        pass
