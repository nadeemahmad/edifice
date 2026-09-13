"""Maintain a governed metadata-only document reading queue."""

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
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

import click

from edifice.identifiers import new_uuid7
from edifice.work_project import get_work_project

INDEX_PATH = Path("20-work/operations/document-library/index.json")
INBOX_PATH = INDEX_PATH.with_name("inbox.md")
CLASSIFICATIONS = frozenset({"public", "netflix-internal", "netflix-confidential"})
READING_STATES = frozenset({"unread", "reading", "read", "changed", "archived"})
PATH_ID = re.compile(
    r"^/(?:document|spreadsheets|presentation)/d/([^/]+)"
    r"|^/file/d/([^/]+)"
    r"|^/drive/(?:u/\d+/)?folders/([^/]+)"
)


@dataclass(frozen=True)
class DriveDocument:
    source_id: str
    source_url: str
    title: str
    mime_type: str
    modified_at: str | None
    viewed_at: str | None
    shared_at: str | None
    version: str | None


@dataclass(frozen=True)
class DocumentLibraryResult:
    action: str
    source_id: str
    inbox_path: Path


@dataclass(frozen=True)
class DocumentSyncResult:
    discovered: int
    added: int
    refreshed: int
    changed: int
    inbox_path: Path


@dataclass(frozen=True)
class DocumentListItem:
    source_id: str
    title: str
    reading_state: str
    categories: tuple[str, ...]
    project_ids: tuple[str, ...]


@dataclass(frozen=True)
class DocumentLibraryStatus:
    total: int
    counts: dict[str, int]


class DocumentSource(Protocol):
    def get_document(self, source_id: str) -> DriveDocument: ...

    def recently_viewed(
        self,
        *,
        days: int,
        limit: int,
    ) -> tuple[DriveDocument, ...]: ...


def add_document(
    *,
    vault_root: Path,
    audit_root: Path,
    source: DocumentSource,
    source_url: str,
    classification: str,
    review_on: date,
    persistence_reason: str,
    project: str | None = None,
) -> DocumentLibraryResult:
    """Resolve and add one authoritative Google document link."""
    source_id = parse_google_source_id(source_url)
    document = source.get_document(source_id)
    if document.source_id != source_id:
        raise click.ClickException("Google document identity mismatch.")
    project_id = _work_project_id(vault_root, project)
    normalized_classification = _classification(classification)
    normalized_reason = persistence_reason.strip()
    if not normalized_reason:
        raise click.ClickException("Persistence reason must not be empty.")
    if review_on < _today():
        raise click.ClickException(
            f"Review date must be today or later: {review_on.isoformat()}"
        )

    now = _now()
    index_path = vault_root / INDEX_PATH
    inbox_path = vault_root / INBOX_PATH
    with _document_library_lock(audit_root):
        index = _load_index(index_path, now)
        documents = cast(dict[str, object], index["documents"])
        previous = documents.get(source_id)
        record = _new_record(
            document=document,
            classification=normalized_classification,
            review_on=review_on,
            persistence_reason=normalized_reason,
            now=now,
            project_id=project_id,
        )
        action = "added"
        if isinstance(previous, dict):
            record = _refresh_record(cast(dict[str, object], previous), record)
            action = "updated"
        documents[source_id] = record
        index["updated_at"] = now.isoformat()
        _replace_atomically(index_path, _json_bytes(index))
        _replace_atomically(inbox_path, _render_inbox(index).encode())
        _append_audit(
            audit_root=audit_root,
            event_type=f"document-library.{action}",
            source_id=source_id,
            document_count=len(documents),
        )
    return DocumentLibraryResult(
        action=action,
        source_id=source_id,
        inbox_path=INBOX_PATH,
    )


def sync_recent_documents(
    *,
    vault_root: Path,
    audit_root: Path,
    source: DocumentSource,
    days: int,
    limit: int,
    classification: str,
    review_on: date,
    persistence_reason: str,
    project: str | None = None,
) -> DocumentSyncResult:
    """Refresh a bounded queue from files recently viewed in Google Drive."""
    if days < 1 or days > 365:
        raise click.ClickException("--days must be between 1 and 365.")
    if limit < 1 or limit > 100:
        raise click.ClickException("--limit must be between 1 and 100.")
    normalized_classification = _classification(classification)
    normalized_reason = persistence_reason.strip()
    if not normalized_reason:
        raise click.ClickException("Persistence reason must not be empty.")
    if review_on < _today():
        raise click.ClickException(
            f"Review date must be today or later: {review_on.isoformat()}"
        )
    discovered = source.recently_viewed(days=days, limit=limit)
    project_id = _work_project_id(vault_root, project)
    now = _now()
    index_path = vault_root / INDEX_PATH
    inbox_path = vault_root / INBOX_PATH
    added = 0
    refreshed_count = 0
    changed = 0
    with _document_library_lock(audit_root):
        index = _load_index(index_path, now)
        documents = cast(dict[str, object], index["documents"])
        for document in discovered:
            next_record = _new_record(
                document=document,
                classification=normalized_classification,
                review_on=review_on,
                persistence_reason=normalized_reason,
                now=now,
                project_id=project_id,
            )
            previous = documents.get(document.source_id)
            if isinstance(previous, dict):
                typed_previous = cast(dict[str, object], previous)
                previous_state = typed_previous.get("reading_state")
                next_record = _refresh_record(
                    typed_previous,
                    next_record,
                )
                refreshed_count += 1
                if (
                    previous_state == "read"
                    and next_record["reading_state"] == "changed"
                ):
                    changed += 1
            else:
                added += 1
            documents[document.source_id] = next_record
        index["updated_at"] = now.isoformat()
        _replace_atomically(index_path, _json_bytes(index))
        _replace_atomically(inbox_path, _render_inbox(index).encode())
        _append_audit(
            audit_root=audit_root,
            event_type="document-library.synced",
            source_id="recently-viewed",
            document_count=len(documents),
        )
    return DocumentSyncResult(
        discovered=len(discovered),
        added=added,
        refreshed=refreshed_count,
        changed=changed,
        inbox_path=INBOX_PATH,
    )


def mark_document(
    *,
    vault_root: Path,
    audit_root: Path,
    document: str,
    state: str,
) -> str:
    """Set owner-controlled reading state for one tracked document."""
    normalized_state = state.strip().lower()
    if normalized_state not in READING_STATES:
        raise click.ClickException(f"Invalid reading state: {state}")
    source_id = _document_argument_id(document)
    now = _now()
    index_path = vault_root / INDEX_PATH
    with _document_library_lock(audit_root):
        index = _load_index(index_path, now)
        documents = cast(dict[str, object], index["documents"])
        record = documents.get(source_id)
        if not isinstance(record, dict):
            raise click.ClickException(f"Document is not tracked: {source_id}")
        typed_record = cast(dict[str, object], record)
        typed_record["reading_state"] = normalized_state
        if normalized_state == "read":
            typed_record["read_version"] = typed_record.get("source_version")
            typed_record["read_at"] = now.isoformat()
        elif normalized_state == "unread":
            typed_record["read_version"] = None
            typed_record["read_at"] = None
        index["updated_at"] = now.isoformat()
        _replace_atomically(index_path, _json_bytes(index))
        _replace_atomically(vault_root / INBOX_PATH, _render_inbox(index).encode())
        _append_audit(
            audit_root=audit_root,
            event_type="document-library.marked",
            source_id=source_id,
            document_count=len(documents),
        )
    return source_id


def categorize_document(
    *,
    vault_root: Path,
    audit_root: Path,
    document: str,
    category: str,
) -> tuple[str, str]:
    """Add one owner-controlled category to a tracked document."""
    source_id = _document_argument_id(document)
    normalized_category = " ".join(category.split())
    if not normalized_category:
        raise click.ClickException("Category must not be empty.")
    if len(normalized_category) > 80:
        raise click.ClickException("Category must contain at most 80 characters.")
    now = _now()
    index_path = vault_root / INDEX_PATH
    with _document_library_lock(audit_root):
        index = _load_index(index_path, now)
        documents = cast(dict[str, object], index["documents"])
        record = documents.get(source_id)
        if not isinstance(record, dict):
            raise click.ClickException(f"Document is not tracked: {source_id}")
        typed_record = cast(dict[str, object], record)
        categories = typed_record.get("categories")
        if not isinstance(categories, list):
            raise click.ClickException(f"Invalid document library: {index_path}")
        typed_categories = cast(list[object], categories)
        if not any(
            isinstance(value, str)
            and value.casefold() == normalized_category.casefold()
            for value in typed_categories
        ):
            typed_categories.append(normalized_category)
        index["updated_at"] = now.isoformat()
        _replace_atomically(index_path, _json_bytes(index))
        _replace_atomically(vault_root / INBOX_PATH, _render_inbox(index).encode())
        _append_audit(
            audit_root=audit_root,
            event_type="document-library.categorized",
            source_id=source_id,
            document_count=len(documents),
        )
    return source_id, normalized_category


def assign_document(
    *,
    vault_root: Path,
    audit_root: Path,
    document: str,
    project: str | None,
) -> str:
    """Assign or unassign one document from a project."""
    source_id = _document_argument_id(document)
    project_id = _work_project_id(vault_root, project)
    now = _now()
    index_path = vault_root / INDEX_PATH
    with _document_library_lock(audit_root):
        index = _load_index(index_path, now)
        documents = cast(dict[str, object], index["documents"])
        value = documents.get(source_id)
        if not isinstance(value, dict):
            raise click.ClickException(f"Document is not tracked: {source_id}")
        record = cast(dict[str, object], value)
        record["project_ids"] = [project_id] if project_id else []
        index["updated_at"] = now.isoformat()
        _replace_atomically(index_path, _json_bytes(index))
        _replace_atomically(vault_root / INBOX_PATH, _render_inbox(index).encode())
        _append_audit(
            audit_root=audit_root,
            event_type="document-library.assigned",
            source_id=source_id,
            document_count=len(documents),
        )
    return source_id


def list_documents(
    *,
    vault_root: Path,
    state: str | None = None,
    project: str | None = None,
) -> tuple[DocumentListItem, ...]:
    """Return tracked documents, optionally filtered by reading state."""
    normalized_state = state.strip().lower() if state is not None else None
    if normalized_state is not None and normalized_state not in READING_STATES:
        raise click.ClickException(f"Invalid reading state: {state}")
    index = _load_index(vault_root / INDEX_PATH, _now())
    project_id = _work_project_id(vault_root, project)
    documents = cast(dict[str, object], index["documents"])
    items: list[DocumentListItem] = []
    for source_id, value in documents.items():
        if not isinstance(value, dict):
            raise click.ClickException(
                f"Invalid document library: {vault_root / INDEX_PATH}"
            )
        record = cast(dict[str, object], value)
        reading_state = record.get("reading_state")
        title = record.get("title")
        categories = record.get("categories")
        project_ids = record.get("project_ids", [])
        if (
            not isinstance(reading_state, str)
            or reading_state not in READING_STATES
            or not isinstance(title, str)
            or not isinstance(categories, list)
            or any(
                not isinstance(category, str)
                for category in cast(list[object], categories)
            )
            or not isinstance(project_ids, list)
            or any(
                not isinstance(project_id, str)
                for project_id in cast(list[object], project_ids)
            )
        ):
            raise click.ClickException(
                f"Invalid document library: {vault_root / INDEX_PATH}"
            )
        if normalized_state is not None and reading_state != normalized_state:
            continue
        if project_id is not None and project_id not in project_ids:
            continue
        items.append(
            DocumentListItem(
                source_id=source_id,
                title=title,
                reading_state=reading_state,
                categories=tuple(cast(list[str], categories)),
                project_ids=tuple(cast(list[str], project_ids)),
            )
        )
    return tuple(
        sorted(items, key=lambda item: (item.reading_state, item.title.casefold()))
    )


def document_library_status(*, vault_root: Path) -> DocumentLibraryStatus:
    """Summarize reading states in the local tracker."""
    items = list_documents(vault_root=vault_root)
    counts = {state: 0 for state in READING_STATES}
    for item in items:
        counts[item.reading_state] += 1
    return DocumentLibraryStatus(total=len(items), counts=counts)


def parse_google_source_id(value: str) -> str:
    """Extract a stable Drive file ID from a supported Google URL."""
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "docs.google.com",
        "drive.google.com",
    }:
        raise click.ClickException("Not a supported Google Docs or Drive URL.")
    match = PATH_ID.match(parsed.path)
    if match is not None:
        return next(group for group in match.groups() if group)
    query_id = parse_qs(parsed.query).get("id")
    if query_id and query_id[0]:
        return query_id[0]
    raise click.ClickException("Google URL does not contain a recognizable file ID.")


def _document_argument_id(value: str) -> str:
    return parse_google_source_id(value) if "://" in value else value.strip()


def _work_project_id(vault_root: Path, project: str | None) -> str | None:
    if project is None:
        return None
    item = get_work_project(vault_root=vault_root, project=project)
    if item.scope != "work":
        raise click.ClickException("Work documents require a work project.")
    return item.project_id


def _new_record(
    *,
    document: DriveDocument,
    classification: str,
    review_on: date,
    persistence_reason: str,
    now: datetime,
    project_id: str | None,
) -> dict[str, object]:
    return {
        "record_id": f"document-record-{new_uuid7()}",
        "provider": "nflx-google",
        "scope": "work",
        "source_id": document.source_id,
        "source_url": document.source_url,
        "title": document.title,
        "mime_type": document.mime_type,
        "modified_at": document.modified_at,
        "viewed_at": document.viewed_at,
        "shared_at": document.shared_at,
        "source_version": document.version,
        "reading_state": "unread",
        "read_version": None,
        "read_at": None,
        "categories": [],
        "project_ids": [project_id] if project_id else [],
        "classification": classification,
        "persistence_reason": persistence_reason,
        "review_on": review_on.isoformat(),
        "added_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "evidence_status": "verified",
    }


def _refresh_record(
    previous: dict[str, object],
    refreshed: dict[str, object],
) -> dict[str, object]:
    for field in (
        "record_id",
        "reading_state",
        "read_version",
        "read_at",
        "categories",
        "project_ids",
        "added_at",
    ):
        refreshed[field] = previous.get(field, refreshed[field])
    if (
        refreshed["reading_state"] == "read"
        and refreshed["read_version"] != refreshed["source_version"]
    ):
        refreshed["reading_state"] = "changed"
    return refreshed


def _load_index(path: Path, now: datetime) -> dict[str, object]:
    if not path.exists():
        return {
            "schema_version": 1,
            "updated_at": now.isoformat(),
            "documents": {},
        }
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read document library: {path}") from error
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid document library: {path}")
    index = cast(dict[str, object], value)
    if (
        set(index) != {"schema_version", "updated_at", "documents"}
        or index.get("schema_version") != 1
        or not isinstance(index.get("updated_at"), str)
        or not isinstance(index.get("documents"), dict)
    ):
        raise click.ClickException(f"Invalid document library: {path}")
    return index


def _render_inbox(index: dict[str, object]) -> str:
    documents = cast(dict[str, object], index["documents"])
    records = [
        cast(dict[str, object], value)
        for value in documents.values()
        if isinstance(value, dict)
    ]
    state_order = {
        "changed": 0,
        "unread": 1,
        "reading": 2,
        "read": 3,
        "archived": 4,
    }
    records.sort(
        key=lambda record: (
            state_order[cast(str, record["reading_state"])],
            -(datetime.fromisoformat(cast(str, record["viewed_at"])).timestamp())
            if record["viewed_at"]
            else 0,
        )
    )
    lines = [
        "---",
        "type: document-reading-inbox",
        "schema_version: 1",
        f"updated: {cast(str, index['updated_at'])}",
        "---",
        "",
        "# Document reading inbox",
        "",
    ]
    if not records:
        lines.append("No documents tracked.")
    for record in records:
        categories = cast(list[object], record["categories"])
        project_ids = cast(list[object], record.get("project_ids", []))
        category_text = (
            ", ".join(f"`{cast(str, category)}`" for category in categories)
            if categories
            else "uncategorized"
        )
        lines.extend(
            [
                (
                    f"- [{record['title']}](<{record['source_url']}>) "
                    f"(`{record['reading_state']}`)"
                ),
                f"  - ID: `{record['source_id']}`",
                f"  - Categories: {category_text}",
                (
                    "  - Projects: "
                    + (
                        ", ".join(
                            f"`{cast(str, project_id)}`" for project_id in project_ids
                        )
                        if project_ids
                        else "unassigned"
                    )
                ),
                f"  - Viewed: `{record['viewed_at'] or 'unavailable'}`",
                f"  - Modified: `{record['modified_at'] or 'unavailable'}`",
                f"  - Review on: `{record['review_on']}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _classification(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in CLASSIFICATIONS:
        raise click.ClickException(f"Invalid work classification: {value}")
    return normalized


def _today() -> date:
    return datetime.now().astimezone().date()


def _now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def _document_library_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        audit_root / "document-library.lock",
        os.O_CREAT | os.O_RDWR,
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _replace_atomically(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _append_audit(
    *,
    audit_root: Path,
    event_type: str,
    source_id: str,
    document_count: int,
) -> None:
    audit_root.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": _now().isoformat(),
        "profile": "work",
        "event_type": event_type,
        "source_id": source_id,
        "document_count": document_count,
        "external_mutation": False,
    }
    path = audit_root / f"{_now().date().isoformat()}.jsonl"
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(
            descriptor,
            f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode(),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
