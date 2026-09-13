"""Create human-owned meeting notes without contacting external systems."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import click

from edifice.identifiers import new_uuid7

MEETING_DIRECTORIES = {
    "personal": Path("10-personal/notes/meetings"),
    "work": Path("20-work/notes/meetings"),
}
MEETING_SERIES_DIRECTORIES = {
    "personal": Path("10-personal/operations/meeting-series"),
    "work": Path("20-work/operations/meeting-series"),
}
SERIES_HISTORY_START = "<!-- edifice:meeting-series-history:start -->"
SERIES_HISTORY_END = "<!-- edifice:meeting-series-history:end -->"
WORK_CLASSIFICATIONS = frozenset({"public", "netflix-internal", "netflix-confidential"})
MAX_SLUG_LENGTH = 120


@dataclass(frozen=True)
class MeetingNoteResult:
    meeting_id: str
    note_path: Path


@dataclass(frozen=True)
class MeetingSeriesResult:
    slug: str
    note_path: Path
    manifest_path: Path


def create_meeting_series(
    *,
    vault_root: Path,
    audit_root: Path,
    title: str,
    scope: str,
    classification: str | None,
) -> MeetingSeriesResult:
    """Create one recurring meeting series without scheduling external events."""
    normalized_title = _normalize_title(title)
    normalized_scope = scope.strip().lower()
    if normalized_scope not in MEETING_DIRECTORIES:
        raise click.ClickException(f"Invalid meeting scope: {scope}")
    normalized_classification = _classification(
        scope=normalized_scope,
        classification=classification,
    )
    created_on = _today()
    slug = _slug(normalized_title)
    series_id = f"meeting-series_{new_uuid7()}"
    note_relative_path = MEETING_DIRECTORIES[normalized_scope] / "series" / f"{slug}.md"
    manifest_relative_path = (
        MEETING_SERIES_DIRECTORIES[normalized_scope] / f"{slug}.json"
    )
    note_path = vault_root / note_relative_path
    manifest_path = vault_root / manifest_relative_path
    note = _render_series_note(
        series_id=series_id,
        slug=slug,
        title=normalized_title,
        scope=normalized_scope,
        classification=normalized_classification,
        created_on=created_on,
    ).encode()
    manifest: dict[str, object] = {
        "schema_version": 1,
        "series_id": series_id,
        "slug": slug,
        "title": normalized_title,
        "scope": normalized_scope,
        "classification": normalized_classification,
        "created": created_on.isoformat(),
        "series_note": note_relative_path.as_posix(),
        "meetings": [],
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()

    with _meeting_lock(audit_root):
        if note_path.exists() or manifest_path.exists():
            raise click.ClickException(f"Meeting series already exists: {slug}")
        _append_series_audit_event(
            audit_root=audit_root,
            event_type="meeting-series.prepared",
            series_id=series_id,
            profile=normalized_scope,
            classification=normalized_classification,
        )
        _write_new_atomically(manifest_path, manifest_bytes)
        try:
            _write_new_atomically(note_path, note)
            _append_series_audit_event(
                audit_root=audit_root,
                event_type="meeting-series.committed",
                series_id=series_id,
                profile=normalized_scope,
                classification=normalized_classification,
            )
        except Exception:
            _remove_unchanged_file(note_path, note)
            _remove_unchanged_file(manifest_path, manifest_bytes)
            raise

    return MeetingSeriesResult(
        slug=slug,
        note_path=note_relative_path,
        manifest_path=manifest_relative_path,
    )


def start_meeting_series(
    *,
    vault_root: Path,
    audit_root: Path,
    slug: str,
    meeting_on: date | None,
) -> MeetingNoteResult:
    """Create one dated occurrence for an existing meeting series."""
    normalized_slug = _validate_slug(slug)
    manifest_path = _find_series_manifest(vault_root, normalized_slug)

    with _meeting_lock(audit_root):
        manifest_before = manifest_path.read_bytes()
        manifest = _load_series_manifest(manifest_path)
        scope = cast(str, manifest["scope"])
        classification = cast(str, manifest["classification"])
        title = cast(str, manifest["title"])
        series_id = cast(str, manifest["series_id"])
        created_on = _today()
        held_on = meeting_on or created_on
        meetings = cast(list[dict[str, str]], manifest["meetings"])
        if any(meeting["meeting_on"] == held_on.isoformat() for meeting in meetings):
            raise click.ClickException(
                f"Meeting already exists for series {normalized_slug}: "
                f"{held_on.isoformat()}"
            )

        previous = _previous_meeting(meetings, held_on)
        meeting_id = f"meeting-note_{new_uuid7()}"
        note_relative_path = (
            MEETING_DIRECTORIES[scope] / f"{held_on.isoformat()}-{normalized_slug}.md"
        )
        note_path = vault_root / note_relative_path
        if note_path.exists():
            raise click.ClickException(
                f"Meeting note already exists: {note_relative_path.name}"
            )

        series_note_relative_path = Path(cast(str, manifest["series_note"]))
        series_note_path = vault_root / series_note_relative_path
        try:
            series_note_before = series_note_path.read_bytes()
        except OSError as error:
            raise click.ClickException(
                f"Meeting series note is unavailable: {series_note_relative_path}"
            ) from error

        note = _render_series_meeting_note(
            meeting_id=meeting_id,
            series_id=series_id,
            series_slug=normalized_slug,
            series_note=series_note_relative_path,
            previous_meeting_path=(
                Path(previous["note_path"]) if previous is not None else None
            ),
            previous_meeting_on=(
                previous["meeting_on"] if previous is not None else None
            ),
            title=title,
            scope=scope,
            classification=classification,
            created_on=created_on,
            meeting_on=held_on,
        ).encode()
        updated_meetings = sorted(
            [
                *meetings,
                {
                    "meeting_id": meeting_id,
                    "meeting_on": held_on.isoformat(),
                    "note_path": note_relative_path.as_posix(),
                },
            ],
            key=lambda meeting: meeting["meeting_on"],
        )
        updated_manifest = dict(manifest)
        updated_manifest["meetings"] = updated_meetings
        manifest_after = (
            json.dumps(
                updated_manifest,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode()
        series_note_after = _replace_series_history(
            series_note_before.decode(),
            updated_meetings,
        ).encode()

        _append_series_meeting_audit_event(
            audit_root=audit_root,
            event_type="meeting-note.prepared",
            meeting_id=meeting_id,
            series_id=series_id,
            profile=scope,
            classification=classification,
            meeting_on=held_on,
            after_hash=_sha256(note),
        )
        _write_new_atomically(note_path, note)
        try:
            _replace_atomically(manifest_path, manifest_after)
            _replace_atomically(series_note_path, series_note_after)
            _append_series_meeting_audit_event(
                audit_root=audit_root,
                event_type="meeting-note.committed",
                meeting_id=meeting_id,
                series_id=series_id,
                profile=scope,
                classification=classification,
                meeting_on=held_on,
                after_hash=_sha256(note),
            )
        except Exception:
            _replace_atomically(manifest_path, manifest_before)
            _replace_atomically(series_note_path, series_note_before)
            _remove_unchanged_file(note_path, note)
            raise

    return MeetingNoteResult(
        meeting_id=meeting_id,
        note_path=note_relative_path,
    )


def create_meeting_note(
    *,
    vault_root: Path,
    audit_root: Path,
    title: str,
    scope: str,
    classification: str | None,
    meeting_on: date | None,
) -> MeetingNoteResult:
    """Create one human-owned meeting note and return its vault path."""
    normalized_title = _normalize_title(title)
    normalized_scope = scope.strip().lower()
    if normalized_scope not in MEETING_DIRECTORIES:
        raise click.ClickException(f"Invalid meeting scope: {scope}")
    normalized_classification = _classification(
        scope=normalized_scope,
        classification=classification,
    )
    created_on = _today()
    held_on = meeting_on or created_on
    meeting_id = f"meeting-note_{new_uuid7()}"
    relative_path = (
        MEETING_DIRECTORIES[normalized_scope]
        / f"{held_on.isoformat()}-{_slug(normalized_title)}.md"
    )
    note_path = vault_root / relative_path
    note = _render_note(
        meeting_id=meeting_id,
        title=normalized_title,
        scope=normalized_scope,
        classification=normalized_classification,
        created_on=created_on,
        meeting_on=held_on,
    ).encode()
    after_hash = _sha256(note)
    with _meeting_lock(audit_root):
        if note_path.exists():
            raise click.ClickException(
                f"Meeting note already exists: {relative_path.name}"
            )
        _append_audit_event(
            audit_root=audit_root,
            event_type="meeting-note.prepared",
            meeting_id=meeting_id,
            profile=normalized_scope,
            classification=normalized_classification,
            meeting_on=held_on,
            after_hash=after_hash,
        )
        _write_new_atomically(note_path, note)
        try:
            _append_audit_event(
                audit_root=audit_root,
                event_type="meeting-note.committed",
                meeting_id=meeting_id,
                profile=normalized_scope,
                classification=normalized_classification,
                meeting_on=held_on,
                after_hash=after_hash,
            )
        except Exception:
            _remove_unchanged_file(note_path, note)
            raise
    return MeetingNoteResult(meeting_id=meeting_id, note_path=relative_path)


def _normalize_title(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise click.ClickException("Meeting title must not be empty.")
    return normalized


def _validate_slug(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise click.ClickException(f"Invalid meeting series: {value}")
    return value


def _classification(*, scope: str, classification: str | None) -> str:
    if scope == "personal":
        if classification is not None and classification.strip().lower() != "personal":
            raise click.ClickException(
                "Personal meeting notes use classification personal."
            )
        return "personal"
    if classification is None:
        raise click.ClickException("Work meeting notes require --classification.")
    normalized = classification.strip().lower()
    if normalized not in WORK_CLASSIFICATIONS:
        raise click.ClickException(f"Invalid work classification: {classification}")
    return normalized


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    if not slug:
        raise click.ClickException("Meeting title must contain letters or numbers.")
    if len(slug) > MAX_SLUG_LENGTH:
        raise click.ClickException(
            "Meeting title produces a filename longer than "
            f"{MAX_SLUG_LENGTH} characters."
        )
    return slug


def _render_note(
    *,
    meeting_id: str,
    title: str,
    scope: str,
    classification: str,
    created_on: date,
    meeting_on: date,
) -> str:
    return f"""---
id: {meeting_id}
type: meeting-note
schema_version: 1
created: {created_on.isoformat()}
ownership: human
scope: {scope}
classification: {json.dumps(classification)}
meeting_on: {meeting_on.isoformat()}
---

# {title}

## Attendees

## Notes

## Decisions

## Action items

- [ ]

## Open questions

## Follow-up
"""


def _render_series_meeting_note(
    *,
    meeting_id: str,
    series_id: str,
    series_slug: str,
    series_note: Path,
    previous_meeting_path: Path | None,
    previous_meeting_on: str | None,
    title: str,
    scope: str,
    classification: str,
    created_on: date,
    meeting_on: date,
) -> str:
    series_link = f"[[{series_note.with_suffix('').as_posix()}]]"
    previous_link = (
        json.dumps(f"[[{previous_meeting_path.with_suffix('').as_posix()}]]")
        if previous_meeting_path is not None
        else "not-applicable"
    )
    carry_forward = (
        (
            f"Previous meeting: "
            f"[[{previous_meeting_path.with_suffix('').as_posix()}"
            f"|{previous_meeting_on}]]\n\n"
            "Review unresolved action items and open questions there."
        )
        if previous_meeting_path is not None
        else "No previous meeting in this series."
    )
    return f"""---
id: {meeting_id}
type: meeting-note
schema_version: 1
created: {created_on.isoformat()}
ownership: human
scope: {scope}
classification: {json.dumps(classification)}
meeting_on: {meeting_on.isoformat()}
series_id: {series_id}
series_slug: {series_slug}
series: {json.dumps(series_link)}
previous_meeting: {previous_link}
---

# {title}

## Preparation

### Carry-forward

{carry_forward}

### Objective

### Topics to discuss

### Questions to ask

### Decisions needed

### Pre-reading

## Attendees

## Notes

## Decisions

## Action items

- [ ]

## Open questions

## Follow-up
"""


def _render_series_note(
    *,
    series_id: str,
    slug: str,
    title: str,
    scope: str,
    classification: str,
    created_on: date,
) -> str:
    return f"""---
id: {series_id}
type: meeting-series
schema_version: 1
created: {created_on.isoformat()}
ownership: human
scope: {scope}
classification: {json.dumps(classification)}
series_slug: {slug}
---

# {title}

## Purpose

## Standing topics

## Preparation defaults

### Questions to ask

### Decisions commonly needed

### Pre-reading

{SERIES_HISTORY_START}
## Meeting history

No meetings captured.
{SERIES_HISTORY_END}
"""


def _find_series_manifest(vault_root: Path, slug: str) -> Path:
    candidates = [
        vault_root / directory / f"{slug}.json"
        for directory in MEETING_SERIES_DIRECTORIES.values()
        if (vault_root / directory / f"{slug}.json").is_file()
    ]
    if not candidates:
        raise click.ClickException(f"Meeting series does not exist: {slug}")
    if len(candidates) > 1:
        raise click.ClickException(
            f"Meeting series is ambiguous across personal and work scopes: {slug}"
        )
    return candidates[0]


def _load_series_manifest(path: Path) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read meeting series: {path}") from error
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid meeting series: {path}")
    manifest = cast(dict[str, object], value)
    required = {
        "schema_version",
        "series_id",
        "slug",
        "title",
        "scope",
        "classification",
        "created",
        "series_note",
        "meetings",
    }
    if set(manifest) != required or manifest.get("schema_version") != 1:
        raise click.ClickException(f"Invalid meeting series: {path}")
    scope = manifest.get("scope")
    classification = manifest.get("classification")
    meetings = manifest.get("meetings")
    if (
        not isinstance(manifest.get("series_id"), str)
        or not isinstance(manifest.get("slug"), str)
        or not isinstance(manifest.get("title"), str)
        or not isinstance(manifest.get("created"), str)
        or not isinstance(manifest.get("series_note"), str)
        or scope not in MEETING_DIRECTORIES
        or not isinstance(classification, str)
        or not isinstance(meetings, list)
    ):
        raise click.ClickException(f"Invalid meeting series: {path}")
    _classification(scope=cast(str, scope), classification=classification)
    if _validate_slug(cast(str, manifest["slug"])) != path.stem:
        raise click.ClickException(f"Invalid meeting series: {path}")
    note_path = Path(cast(str, manifest["series_note"]))
    expected_note_root = MEETING_DIRECTORIES[cast(str, scope)] / "series"
    if (
        note_path.is_absolute()
        or ".." in note_path.parts
        or note_path.suffix != ".md"
        or note_path.parent != expected_note_root
    ):
        raise click.ClickException(f"Invalid meeting series: {path}")
    seen_dates: set[str] = set()
    seen_paths: set[str] = set()
    for item in cast(list[object], meetings):
        if not isinstance(item, dict):
            raise click.ClickException(f"Invalid meeting series: {path}")
        meeting = cast(dict[str, object], item)
        if set(meeting) != {"meeting_id", "meeting_on", "note_path"} or any(
            not isinstance(meeting.get(field), str)
            for field in ("meeting_id", "meeting_on", "note_path")
        ):
            raise click.ClickException(f"Invalid meeting series: {path}")
        meeting_on = cast(str, meeting["meeting_on"])
        note_path_text = cast(str, meeting["note_path"])
        if meeting_on in seen_dates or note_path_text in seen_paths:
            raise click.ClickException(f"Invalid meeting series: {path}")
        seen_dates.add(meeting_on)
        seen_paths.add(note_path_text)
    return manifest


def _previous_meeting(
    meetings: list[dict[str, str]],
    meeting_on: date,
) -> dict[str, str] | None:
    earlier = [
        meeting
        for meeting in meetings
        if meeting["meeting_on"] < meeting_on.isoformat()
    ]
    return max(earlier, key=lambda meeting: meeting["meeting_on"], default=None)


def _replace_series_history(
    content: str,
    meetings: list[dict[str, str]],
) -> str:
    lines = ["## Meeting history", ""]
    lines.extend(
        (
            f"- [[{Path(meeting['note_path']).with_suffix('').as_posix()}"
            f"|{meeting['meeting_on']}]]"
        )
        for meeting in meetings
    )
    return _replace_marked_section(
        content,
        SERIES_HISTORY_START,
        SERIES_HISTORY_END,
        "\n".join(lines),
    )


def _replace_marked_section(
    content: str,
    start_marker: str,
    end_marker: str,
    body: str,
) -> str:
    if content.count(start_marker) != 1 or content.count(end_marker) != 1:
        raise click.ClickException("Meeting series history markers are invalid.")
    start = content.index(start_marker) + len(start_marker)
    end = content.index(end_marker)
    if end < start:
        raise click.ClickException("Meeting series history markers are invalid.")
    return f"{content[:start]}\n{body}\n{content[end:]}"


def _today() -> date:
    return datetime.now().astimezone().date()


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


@contextmanager
def _meeting_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / "meeting-note.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _append_audit_event(
    *,
    audit_root: Path,
    event_type: str,
    meeting_id: str,
    profile: str,
    classification: str,
    meeting_on: date,
    after_hash: str,
) -> None:
    now = datetime.now(UTC)
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": now.isoformat(),
        "profile": profile,
        "event_type": event_type,
        "meeting_id": meeting_id,
        "classification": classification,
        "meeting_on": meeting_on.isoformat(),
        "after_hash": after_hash,
    }
    encoded = f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode()
    audit_path = audit_root / f"{now.date().isoformat()}.jsonl"
    descriptor = os.open(
        audit_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_series_audit_event(
    *,
    audit_root: Path,
    event_type: str,
    series_id: str,
    profile: str,
    classification: str,
) -> None:
    now = datetime.now(UTC)
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": now.isoformat(),
        "profile": profile,
        "event_type": event_type,
        "series_id": series_id,
        "classification": classification,
    }
    encoded = f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode()
    audit_path = audit_root / f"{now.date().isoformat()}.jsonl"
    descriptor = os.open(
        audit_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _append_series_meeting_audit_event(
    *,
    audit_root: Path,
    event_type: str,
    meeting_id: str,
    series_id: str,
    profile: str,
    classification: str,
    meeting_on: date,
    after_hash: str,
) -> None:
    now = datetime.now(UTC)
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": now.isoformat(),
        "profile": profile,
        "event_type": event_type,
        "meeting_id": meeting_id,
        "series_id": series_id,
        "classification": classification,
        "meeting_on": meeting_on.isoformat(),
        "after_hash": after_hash,
    }
    encoded = f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode()
    audit_path = audit_root / f"{now.date().isoformat()}.jsonl"
    descriptor = os.open(
        audit_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
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
            f"Meeting note already exists: {target.name}"
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
