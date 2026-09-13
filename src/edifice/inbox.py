"""Collect and review Inbox captures without losing their raw records."""

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import click

from edifice.identifiers import new_uuid7

INBOX_PATH = Path("01-inbox/inbox.md")
ROUTING_PATH = Path("10-personal/operations/inbox/routing.json")
REVIEW_PATH = Path("10-personal/operations/inbox/review.md")
CAPTURE_PATTERN = re.compile(
    r"^- \[(?P<checked>[ xX])\] "
    r"(?P<text>.*?)(?: \^(?P<capture_id>capture-[0-9a-f-]{36}))?$"
)
EXPLICIT_ROUTE_PREFIXES = {
    "work task:": "current-work-task",
    "work note:": "current-work-note",
    "work question:": "current-work-question",
    "work idea:": "work-idea",
    "personal task:": "personal-project-task",
    "personal note:": "personal-project-note",
    "personal question:": "personal-project-question",
    "personal idea:": "personal-idea",
}
ROUTES = frozenset(
    {
        "current-work-task",
        "current-work-note",
        "current-work-question",
        "work-idea",
        "personal-project-task",
        "personal-project-note",
        "personal-project-question",
        "personal-idea",
        "archive",
    }
)
CURRENT_POINTER_PATH = Path("00-system/current.json")
PERSONAL_IDEA_PATH = Path("10-personal/ai/ideas/capture-ideas.md")
WORK_IDEA_PATH = Path("20-work/operations/ideas/seeds.md")
WORK_CLASSIFICATIONS = frozenset({"public", "netflix-internal", "netflix-confidential"})


@dataclass(frozen=True)
class Capture:
    capture_id: str
    text: str
    checked: bool
    line_index: int


@dataclass(frozen=True)
class InboxProcessResult:
    processed: int
    needs_review: int
    routing_failures: int
    review_path: Path


@dataclass(frozen=True)
class InboxRouteResult:
    capture_id: str
    destination: str
    already_routed: bool


@dataclass(frozen=True)
class InboxReviewItem:
    capture_id: str
    text: str
    suggested_route: str
    evidence_status: str


def process_inbox(*, vault_root: Path, audit_root: Path) -> InboxProcessResult:
    """Identify unchecked captures and refresh their routing review."""
    inbox_path = vault_root / INBOX_PATH
    routing_path = vault_root / ROUTING_PATH
    review_path = vault_root / REVIEW_PATH

    with _inbox_lock(audit_root):
        lines = _read_inbox(inbox_path)
        captures, updated_lines = _identify_captures(lines)
        if updated_lines != lines:
            _replace_atomically(
                inbox_path,
                ("\n".join(updated_lines).rstrip() + "\n").encode(),
            )

        now = _now()
        routing = _load_routing(routing_path, now)
        records = cast(dict[str, object], routing["captures"])
        current_ids = {capture.capture_id for capture in captures}
        for capture in captures:
            if capture.checked:
                continue
            source_hash = _source_hash(capture.text)
            previous = records.get(capture.capture_id)
            if isinstance(previous, dict):
                typed_previous = cast(dict[str, object], previous)
                if typed_previous.get("source_hash") not in {None, source_hash}:
                    typed_previous["status"] = "routing-failed"
                    typed_previous["failure"] = (
                        "Capture text changed after identification."
                    )
                    typed_previous["updated_at"] = now.isoformat()
                    continue
                if typed_previous.get("status") in {
                    "routed",
                    "routing",
                    "routing-failed",
                }:
                    continue
            suggested_route, evidence_status = _suggest_route(capture.text)
            records[capture.capture_id] = {
                "source_hash": source_hash,
                "status": "needs-review",
                "suggested_route": suggested_route,
                "evidence_status": evidence_status,
                "destination": None,
                "route_id": None,
                "updated_at": now.isoformat(),
            }

        _reconcile_records(
            vault_root=vault_root,
            captures=captures,
            current_ids=current_ids,
            records=records,
            now=now,
        )

        routing["updated_at"] = now.isoformat()
        _replace_atomically(
            routing_path,
            (json.dumps(routing, indent=2, sort_keys=True) + "\n").encode(),
        )
        _replace_atomically(
            review_path,
            _render_review(captures, records, now).encode(),
        )

    needs_review = len(_capture_ids_with_status(records, "needs-review"))
    routing_failures = len(_capture_ids_with_status(records, "routing-failed"))
    return InboxProcessResult(
        processed=sum(not capture.checked for capture in captures),
        needs_review=needs_review,
        routing_failures=routing_failures,
        review_path=REVIEW_PATH,
    )


def review_items(*, vault_root: Path) -> tuple[InboxReviewItem, ...]:
    """Return unresolved captures in Inbox order for interactive review."""
    captures, _ = _identify_captures(_read_inbox(vault_root / INBOX_PATH))
    routing = _load_routing(vault_root / ROUTING_PATH, _now())
    records = cast(dict[str, object], routing["captures"])
    items: list[InboxReviewItem] = []
    for capture in captures:
        record = _as_record(records.get(capture.capture_id))
        if record is None or record.get("status") != "needs-review":
            continue
        suggested_route = record.get("suggested_route")
        evidence_status = record.get("evidence_status")
        if not isinstance(suggested_route, str) or not isinstance(evidence_status, str):
            raise click.ClickException(
                f"Capture has an invalid routing record: {capture.capture_id}"
            )
        items.append(
            InboxReviewItem(
                capture_id=capture.capture_id,
                text=capture.text,
                suggested_route=suggested_route,
                evidence_status=evidence_status,
            )
        )
    return tuple(items)


def route_capture(
    *,
    vault_root: Path,
    audit_root: Path,
    capture_id: str,
    route: str,
    classification: str | None = None,
) -> InboxRouteResult:
    """Route one identified capture while preserving its Inbox record."""
    if route not in ROUTES:
        raise click.ClickException(f"Invalid Inbox route: {route}")
    normalized_classification = (
        classification.strip().lower() if classification is not None else None
    )
    if route != "work-idea" and normalized_classification is not None:
        raise click.ClickException(
            "Classification is allowed only for work-idea routes."
        )
    if route == "work-idea" and normalized_classification not in WORK_CLASSIFICATIONS:
        raise click.ClickException(
            "Work ideas require --classification public, "
            "netflix-internal, or netflix-confidential."
        )
    inbox_path = vault_root / INBOX_PATH
    routing_path = vault_root / ROUTING_PATH
    review_path = vault_root / REVIEW_PATH

    with _inbox_lock(audit_root):
        lines = _read_inbox(inbox_path)
        captures, updated_lines = _identify_captures(lines)
        capture = next(
            (item for item in captures if item.capture_id == capture_id),
            None,
        )
        if capture is None:
            raise click.ClickException(f"Capture does not exist: {capture_id}")

        now = _now()
        routing = _load_routing(routing_path, now)
        records = cast(dict[str, object], routing["captures"])
        source_hash = _source_hash(capture.text)
        previous = records.get(capture_id)
        record = _as_record(previous)
        if record is not None:
            if record.get("source_hash") not in {None, source_hash}:
                raise click.ClickException(
                    f"Capture changed after routing review: {capture_id}"
                )
            recorded_route = record.get("suggested_route")
            if (
                record.get("status") in {"routing", "routing-failed"}
                and recorded_route in ROUTES
            ):
                if recorded_route != route:
                    raise click.ClickException(
                        f"Capture has incomplete route {recorded_route}."
                    )
                if (
                    route == "work-idea"
                    and record.get("classification") != normalized_classification
                ):
                    raise click.ClickException(
                        "Capture has incomplete work-idea classification "
                        f"{record.get('classification')}."
                    )
            if record.get("status") == "routed":
                destination = record.get("destination")
                route_id = record.get("route_id")
                if not isinstance(destination, str):
                    raise click.ClickException(
                        f"Routed capture has no destination: {capture_id}"
                    )
                failure = _destination_failure(
                    vault_root=vault_root,
                    destination=destination,
                    route_id=route_id,
                )
                if failure is None and capture.checked:
                    completed_route = record.get("suggested_route")
                    if completed_route != route:
                        raise click.ClickException(
                            "Capture already completed through route "
                            f"{completed_route}."
                        )
                    if (
                        route == "work-idea"
                        and record.get("classification") != normalized_classification
                    ):
                        raise click.ClickException(
                            "Capture already completed with classification "
                            f"{record.get('classification')}."
                        )
                    return InboxRouteResult(
                        capture_id=capture_id,
                        destination=destination,
                        already_routed=True,
                    )
                record["status"] = "routing-failed"
                record["failure"] = failure or "Source capture is not marked routed."
                record["updated_at"] = now.isoformat()
            elif record.get("status") == "archived":
                if capture.checked:
                    if route != "archive":
                        raise click.ClickException(
                            "Capture already completed through route archive."
                        )
                    return InboxRouteResult(
                        capture_id=capture_id,
                        destination="archive",
                        already_routed=True,
                    )
                record["status"] = "routing-failed"
                record["failure"] = "Archived capture is not marked processed."
                record["updated_at"] = now.isoformat()
        elif capture.checked:
            raise click.ClickException(
                f"Capture is checked without a routing record: {capture_id}"
            )

        if route == "archive":
            archive_id = (
                cast(str, record["route_id"])
                if record is not None
                and record.get("status") == "routing-failed"
                and isinstance(record.get("route_id"), str)
                else f"archive-{new_uuid7()}"
            )
            records[capture_id] = {
                "source_hash": source_hash,
                "status": "archived",
                "suggested_route": "archive",
                "evidence_status": "owner-attested",
                "destination": None,
                "route_id": archive_id,
                "disposition": "archived",
                "classification": None,
                "updated_at": now.isoformat(),
            }
            routing["updated_at"] = now.isoformat()
            updated_lines = _mark_capture_archived(
                updated_lines,
                capture=capture,
                archive_id=archive_id,
            )
            _replace_atomically(
                inbox_path,
                ("\n".join(updated_lines).rstrip() + "\n").encode(),
            )
            _replace_atomically(
                routing_path,
                (json.dumps(routing, indent=2, sort_keys=True) + "\n").encode(),
            )
            archived_captures, _ = _identify_captures(updated_lines)
            _replace_atomically(
                review_path,
                _render_review(archived_captures, records, now).encode(),
            )
            _append_disposition_audit_event(
                audit_root=audit_root,
                event_type="capture.archived",
                capture_id=capture_id,
                route_id=archive_id,
                destination=None,
                source_hash=source_hash,
                now=now,
            )
            return InboxRouteResult(
                capture_id=capture_id,
                destination="archive",
                already_routed=False,
            )

        target_path, heading, anchor = _resolve_destination(
            vault_root=vault_root,
            route=route,
        )
        target_relative_path = target_path.relative_to(vault_root)
        destination = f"{target_relative_path.as_posix()}#{anchor}"
        route_id = (
            cast(str, record["route_id"])
            if record is not None
            and record.get("status") in {"routing", "routing-failed"}
            and record.get("destination") == destination
            and isinstance(record.get("route_id"), str)
            else f"route-{new_uuid7()}"
        )
        records[capture_id] = {
            "source_hash": source_hash,
            "status": "routing",
            "suggested_route": route,
            "evidence_status": "owner-attested",
            "destination": destination,
            "route_id": route_id,
            "classification": normalized_classification,
            "updated_at": now.isoformat(),
        }
        routing["updated_at"] = now.isoformat()
        _replace_atomically(
            routing_path,
            (json.dumps(routing, indent=2, sort_keys=True) + "\n").encode(),
        )

        if target_path.exists():
            target = target_path.read_text(encoding="utf-8")
        elif route == "personal-idea":
            target = _new_personal_idea_note(now.astimezone().date().isoformat())
        elif route == "work-idea":
            target = _new_work_idea_note(now.astimezone().date().isoformat())
        else:
            raise click.ClickException(
                f"Selected work note does not exist: {target_relative_path}"
            )
        routed_item = _routed_item(
            capture=capture,
            route=route,
            route_id=route_id,
            classification=normalized_classification,
        )
        if f"`{route_id}`" not in target:
            target = _append_to_heading(target, heading, routed_item)
            _replace_atomically(target_path, target.encode())

        updated_lines = _mark_capture_routed(
            updated_lines,
            capture=capture,
            destination=destination,
            route_id=route_id,
        )
        _replace_atomically(
            inbox_path,
            ("\n".join(updated_lines).rstrip() + "\n").encode(),
        )

        record = cast(dict[str, object], records[capture_id])
        record["status"] = "routed"
        record["updated_at"] = now.isoformat()
        _replace_atomically(
            routing_path,
            (json.dumps(routing, indent=2, sort_keys=True) + "\n").encode(),
        )
        routed_captures, _ = _identify_captures(updated_lines)
        _replace_atomically(
            review_path,
            _render_review(routed_captures, records, now).encode(),
        )
        _append_disposition_audit_event(
            audit_root=audit_root,
            event_type="capture.routed",
            capture_id=capture_id,
            route_id=route_id,
            destination=destination,
            source_hash=source_hash,
            now=now,
        )

    return InboxRouteResult(
        capture_id=capture_id,
        destination=destination,
        already_routed=False,
    )


def preview_route(*, vault_root: Path, route: str) -> str:
    """Return the local effect of a route without changing vault state."""
    if route == "archive":
        return "archive"
    target_path, _heading, anchor = _resolve_destination(
        vault_root=vault_root,
        route=route,
    )
    relative_path = target_path.relative_to(vault_root)
    return f"{relative_path.as_posix()}#{anchor}"


def _read_inbox(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise click.ClickException(f"Cannot read {path}") from error


def _identify_captures(lines: list[str]) -> tuple[list[Capture], list[str]]:
    captures: list[Capture] = []
    updated_lines = list(lines)
    seen_ids: set[str] = set()
    for index, line in enumerate(lines):
        match = CAPTURE_PATTERN.fullmatch(line)
        if match is None:
            continue
        text = match.group("text").strip()
        if not text:
            continue
        checked = match.group("checked").lower() == "x"
        capture_id = match.group("capture_id")
        if capture_id is None and checked:
            continue
        capture_id = capture_id or f"capture-{new_uuid7()}"
        if capture_id in seen_ids:
            raise click.ClickException(f"Duplicate capture ID: {capture_id}")
        seen_ids.add(capture_id)
        captures.append(
            Capture(
                capture_id=capture_id,
                text=text,
                checked=checked,
                line_index=index,
            )
        )
        if match.group("capture_id") is None:
            updated_lines[index] = f"- [ ] {text} ^{capture_id}"
    return captures, updated_lines


def _reconcile_records(
    *,
    vault_root: Path,
    captures: list[Capture],
    current_ids: set[str],
    records: dict[str, object],
    now: datetime,
) -> None:
    captures_by_id = {capture.capture_id: capture for capture in captures}
    for capture_id, value in records.items():
        if not isinstance(value, dict):
            continue
        record = cast(dict[str, object], value)
        capture = captures_by_id.get(capture_id)
        if capture_id not in current_ids or capture is None:
            record["status"] = "routing-failed"
            record["failure"] = "Capture is unavailable in the Inbox."
            record["updated_at"] = now.isoformat()
            continue
        if record.get("source_hash") != _source_hash(capture.text):
            record["status"] = "routing-failed"
            record["failure"] = "Capture text changed after routing review."
            record["updated_at"] = now.isoformat()
            continue
        status = record.get("status")
        if status == "routed":
            destination = record.get("destination")
            if not isinstance(destination, str):
                failure = "Routed capture has no destination."
            else:
                failure = _destination_failure(
                    vault_root=vault_root,
                    destination=destination,
                    route_id=record.get("route_id"),
                )
            if failure is None and not capture.checked:
                failure = "Source capture is not marked routed."
            if failure is not None:
                record["status"] = "routing-failed"
                record["failure"] = failure
                record["updated_at"] = now.isoformat()
        elif status == "routing":
            record["status"] = "routing-failed"
            record["failure"] = "Routing was interrupted; rerun the route command."
            record["updated_at"] = now.isoformat()
        elif status == "archived":
            if not capture.checked:
                record["status"] = "routing-failed"
                record["failure"] = "Archived capture is not marked processed."
                record["updated_at"] = now.isoformat()
        elif capture.checked:
            record["status"] = "routing-failed"
            record["failure"] = "Capture is checked without a completed route."
            record["updated_at"] = now.isoformat()


def _destination_failure(
    *,
    vault_root: Path,
    destination: str,
    route_id: object,
) -> str | None:
    path_text, _, _anchor = destination.partition("#")
    relative_path = Path(path_text)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return "Routed destination is unsafe."
    path = vault_root / relative_path
    if not path.is_file():
        return "Routed destination is unavailable."
    if not isinstance(route_id, str) or not route_id:
        return "Routed capture has no route identifier."
    try:
        destination_note = path.read_text(encoding="utf-8")
    except OSError:
        return "Routed destination is unavailable."
    if f"`{route_id}`" not in destination_note:
        return "Routed destination no longer contains the route record."
    return None


def _resolve_destination(
    *,
    vault_root: Path,
    route: str,
) -> tuple[Path, str, str]:
    if route == "personal-idea":
        path = vault_root / PERSONAL_IDEA_PATH
        return path, "## Captures", "captures"
    if route == "work-idea":
        path = vault_root / WORK_IDEA_PATH
        return path, "## Seeds", "seeds"

    current_path = vault_root / CURRENT_POINTER_PATH
    try:
        current: object = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {current_path}") from error
    if not isinstance(current, dict):
        raise click.ClickException("Current-state pointer must be a JSON object.")
    typed_current = cast(dict[str, object], current)
    work = typed_current.get("work")
    if not isinstance(work, str) or not work:
        raise click.ClickException("Current-state pointer is missing: work")
    relative_path = Path(work)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise click.ClickException(f"Unsafe current work pointer: {work}")
    personal_route = route.startswith("personal-project-")
    expected_directory = (
        ("10-personal", "operations", "projects")
        if personal_route
        else ("20-work", "operations", "projects")
    )
    if relative_path.parts[:3] != expected_directory:
        expected = "/".join(expected_directory)
        raise click.ClickException(f"The selected project is not under {expected}.")
    path = vault_root / relative_path
    if not path.is_file():
        raise click.ClickException(f"Selected work note does not exist: {work}")
    if route == "current-work-task":
        note = path.read_text(encoding="utf-8")
        if "## Tasks" in note.splitlines():
            return path, "## Tasks", "tasks"
        if "### Next action" in note.splitlines():
            return path, "### Next action", "next-action"
        raise click.ClickException(
            "Destination section is missing: ## Tasks or ### Next action"
        )
    headings = {
        "current-work-note": ("### Notes", "notes"),
        "current-work-question": ("### Questions", "questions"),
        "personal-project-task": ("## Tasks", "tasks"),
        "personal-project-note": ("## Current state", "current-state"),
        "personal-project-question": ("## Questions", "questions"),
    }
    heading, anchor = headings[route]
    return path, heading, anchor


def _routed_item(
    *,
    capture: Capture,
    route: str,
    route_id: str,
    classification: str | None,
) -> str:
    task_routes = {"current-work-task", "personal-project-task"}
    prefix = "- [ ] " if route in task_routes else "- "
    lines = [
        f"{prefix}{capture.text}",
        f"  - Source: [[01-inbox/inbox#^{capture.capture_id}|capture]]",
    ]
    if classification is not None:
        lines.append(f"  - Classification: `{classification}`")
    lines.append(f"  - Route: `{route_id}`")
    return "\n".join(lines)


def _append_to_heading(note: str, heading: str, item: str) -> str:
    lines = note.splitlines()
    try:
        heading_index = lines.index(heading)
    except ValueError as error:
        raise click.ClickException(
            f"Destination section is missing: {heading}"
        ) from error
    heading_level = len(heading) - len(heading.lstrip("#"))
    insertion_index = len(lines)
    for index in range(heading_index + 1, len(lines)):
        line = lines[index]
        if not line.startswith("#"):
            continue
        level = len(line) - len(line.lstrip("#"))
        if level <= heading_level:
            insertion_index = index
            break
    while insertion_index > heading_index + 1 and lines[insertion_index - 1] == "":
        insertion_index -= 1
    new_lines = [*lines[:insertion_index]]
    if new_lines and new_lines[-1] != "":
        new_lines.append("")
    new_lines.extend(item.splitlines())
    new_lines.extend(["", *lines[insertion_index:]])
    return "\n".join(new_lines).rstrip() + "\n"


def _mark_capture_routed(
    lines: list[str],
    *,
    capture: Capture,
    destination: str,
    route_id: str,
) -> list[str]:
    updated = list(lines)
    updated[capture.line_index] = f"- [x] {capture.text} ^{capture.capture_id}"
    route_line = f"  - Route: `{route_id}`"
    if route_line in updated:
        return updated
    updated[capture.line_index + 1 : capture.line_index + 1] = [
        f"  - Routed: [[{destination}|destination]]",
        route_line,
    ]
    return updated


def _mark_capture_archived(
    lines: list[str],
    *,
    capture: Capture,
    archive_id: str,
) -> list[str]:
    updated = list(lines)
    updated[capture.line_index] = f"- [x] {capture.text} ^{capture.capture_id}"
    archive_line = f"  - Archive: `{archive_id}`"
    if archive_line in updated:
        return updated
    updated[capture.line_index + 1 : capture.line_index + 1] = [
        "  - Disposition: `archived`",
        archive_line,
    ]
    return updated


def _new_personal_idea_note(created_on: str) -> str:
    return f"""---
type: ai-workspace
schema_version: 1
created: {created_on}
status: active
---

# Captured idea seeds

These are routed source captures, not owner commitments.

## Captures
"""


def _new_work_idea_note(created_on: str) -> str:
    return f"""---
id: idea-seeds_{new_uuid7()}
type: idea-seeds
schema_version: 1
created: {created_on}
status: active
scope: work
classification: per-entry
---

# Work idea seeds

Ideas are not tasks or project commitments until the owner promotes them.

## Seeds
"""


def _load_routing(path: Path, now: datetime) -> dict[str, object]:
    if not path.exists():
        return {
            "schema_version": 1,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "captures": {},
        }
    try:
        routing: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {path}") from error
    if not isinstance(routing, dict):
        raise click.ClickException("Inbox routing ledger has an invalid structure.")
    typed_routing = cast(dict[str, object], routing)
    if not isinstance(typed_routing.get("captures"), dict):
        raise click.ClickException("Inbox routing ledger has an invalid structure.")
    return typed_routing


def _suggest_route(text: str) -> tuple[str, str]:
    normalized = text.casefold()
    for prefix, route in EXPLICIT_ROUTE_PREFIXES.items():
        if normalized.startswith(prefix):
            return route, "owner-attested"
    return "review", "unavailable"


def _render_review(
    captures: list[Capture],
    records: dict[str, object],
    now: datetime,
) -> str:
    captures_by_id = {capture.capture_id: capture for capture in captures}
    needs_review = _capture_ids_with_status(records, "needs-review")
    failures = _capture_ids_with_status(records, "routing-failed")
    routed = _capture_ids_with_status(records, "routed")
    archived = _capture_ids_with_status(records, "archived")
    lines = [
        "---",
        "type: inbox-routing-review",
        "schema_version: 1",
        f"created: {now.astimezone().date().isoformat()}",
        f"updated_at: {now.isoformat()}",
        "status: active",
        "---",
        "",
        "# Inbox routing review",
        "",
        "## Summary",
        "",
        f"- Needs review: {len(needs_review)}",
        f"- Routing failures: {len(failures)}",
        f"- Routed: {len(routed)}",
        f"- Archived: {len(archived)}",
        "",
        "## Needs review",
        "",
    ]
    if not needs_review:
        lines.append("- None.")
    for capture_id in needs_review:
        record = cast(dict[str, object], records[capture_id])
        capture = captures_by_id.get(capture_id)
        text = capture.text if capture is not None else "Capture unavailable."
        suggested_route = cast(str, record["suggested_route"])
        lines.extend(
            [
                f"### {capture_id}",
                "",
                f"> {text}",
                "",
                f"- Suggested route: `{suggested_route}`",
                f"- Evidence: `{record['evidence_status']}`",
            ]
        )
        if suggested_route == "review":
            lines.append("- No route was inferred.")
        else:
            lines.append(
                f"- Apply: `edifice inbox route {capture_id} --to {suggested_route}`"
            )
        lines.append("")
    lines.extend(["## Routing failures", ""])
    if not failures:
        lines.append("- None.")
    for capture_id in failures:
        record = cast(dict[str, object], records[capture_id])
        lines.append(
            f"- `{capture_id}`: {record.get('failure', 'Reconciliation failed.')}"
        )
    lines.extend(["", "## Routed", ""])
    if not routed:
        lines.append("- None.")
    for capture_id in routed:
        record = cast(dict[str, object], records[capture_id])
        lines.append(f"- `{capture_id}` -> `{record.get('destination')}`")
    lines.extend(["", "## Archived", ""])
    if not archived:
        lines.append("- None.")
    for capture_id in archived:
        lines.append(f"- `{capture_id}`")
    return "\n".join(lines).rstrip() + "\n"


def _capture_ids_with_status(
    records: dict[str, object],
    status: str,
) -> list[str]:
    capture_ids: list[str] = []
    for capture_id, value in records.items():
        record = _as_record(value)
        if record is not None and record.get("status") == status:
            capture_ids.append(capture_id)
    return capture_ids


def _as_record(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _source_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def _now() -> datetime:
    return datetime.now(UTC)


def _append_disposition_audit_event(
    *,
    audit_root: Path,
    event_type: str,
    capture_id: str,
    route_id: str,
    destination: str | None,
    source_hash: str,
    now: datetime,
) -> None:
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": now.isoformat(),
        "profile": "personal",
        "event_type": event_type,
        "capture_id": capture_id,
        "route_id": route_id,
        "destination": destination,
        "source_hash": source_hash,
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


@contextmanager
def _inbox_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / "capture.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
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
        mode = path.stat().st_mode if path.exists() else 0o644
        temporary_path.chmod(mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
