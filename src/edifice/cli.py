import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import click

from edifice.adobe_import import (
    apply_adobe_import,
    default_adobe_cache_roots,
    plan_adobe_import,
)
from edifice.document_review import (
    add_review_document,
    ensure_review_document_capacity,
    find_review_document,
    gather_review,
    get_review_status,
    load_review_manifest,
    normalize_review_metadata,
    normalize_review_source,
    review_paths,
    start_review,
    synthesize_review,
)
from edifice.identifiers import new_uuid7
from edifice.inbox import (
    ROUTES,
    InboxProcessResult,
    InboxReviewItem,
    InboxRouteResult,
    preview_route,
    process_inbox,
    review_items,
    route_capture,
)
from edifice.meeting_note import (
    create_meeting_note,
    create_meeting_series,
    start_meeting_series,
)
from edifice.migration import (
    apply_migration,
    approve_migration_batch,
    inventory_source_directory,
    migration_status,
    plan_migration,
    verify_migration_package,
)
from edifice.pdf_library import (
    DOCUMENT_KINDS,
    add_pdf,
    backup_personal_pdfs,
    inventory_pdfs,
)
from edifice.work_context import gather_work_context
from edifice.work_task import start_work_task


@dataclass(frozen=True)
class RuntimePaths:
    vault_root: Path
    audit_root: Path
    personal_library_root: Path | None
    migrations_root: Path | None
    dry_run: bool


REQUIRED_VAULT_FILES = (
    Path("AGENTS.md"),
    Path("home.md"),
    Path("00-system/operating-manual.md"),
    Path("00-system/soul.md"),
    Path("00-system/schema.md"),
    Path("00-system/workflows.md"),
    Path("00-system/current.json"),
    Path("00-system/engineering/owner-practices.md"),
    Path("00-system/templates/document-review.md"),
    Path("00-system/templates/document-review-ai.md"),
    Path("01-inbox/inbox.md"),
    Path("10-personal/artifacts/AGENTS.md"),
    Path("10-personal/notes/imported/AGENTS.md"),
    Path("10-personal/operations/artifacts/imports/AGENTS.md"),
    Path("10-personal/operations/migrations/AGENTS.md"),
    Path(".obsidian/core-plugins.json"),
)

REQUIRED_WORK_FILES = (
    Path("00-system/work-context-policy.md"),
    Path("20-work/AGENTS.md"),
    Path("20-work/references/document-reviews/AGENTS.md"),
)


@click.group()
@click.option(
    "--vault",
    "vault_root",
    envvar="EDIFICE_VAULT",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option(
    "--audit-root",
    envvar="EDIFICE_AUDIT_ROOT",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option(
    "--personal-library",
    "personal_library_root",
    envvar="EDIFICE_PERSONAL_LIBRARY",
    type=click.Path(path_type=Path, file_okay=False),
    help="Personal Google Drive library path.",
)
@click.option(
    "--migrations-root",
    envvar="EDIFICE_MIGRATIONS_ROOT",
    type=click.Path(path_type=Path, file_okay=False),
    help="Machine-local migration package root.",
)
@click.option("--dry-run", is_flag=True, help="Show effects without opening Obsidian.")
@click.pass_context
def cli(
    context: click.Context,
    vault_root: Path,
    audit_root: Path,
    personal_library_root: Path | None,
    migrations_root: Path | None,
    dry_run: bool,
) -> None:
    """Operate the local Edifice system."""
    context.obj = RuntimePaths(
        vault_root=vault_root,
        audit_root=audit_root,
        personal_library_root=personal_library_root,
        migrations_root=migrations_root,
        dry_run=dry_run,
    )


@cli.command()
@click.argument("text")
@click.pass_obj
def capture(paths: RuntimePaths, text: str) -> None:
    """Preserve text in the canonical inbox."""
    audit_path = _audit_path(paths.audit_root)
    with _capture_lock(paths.audit_root):
        capture_id = f"capture-{new_uuid7()}"
        inbox_path = paths.vault_root / "01-inbox" / "inbox.md"
        before = inbox_path.read_bytes()
        after = before + f"- [ ] {text} ^{capture_id}\n".encode()
        before_hash = _sha256(before)
        after_hash = _sha256(after)

        _append_audit_event(
            audit_path,
            event_type="capture.prepared",
            capture_id=capture_id,
            before_hash=before_hash,
            after_hash=after_hash,
        )
        _replace_atomically(inbox_path, after)
        _append_audit_event(
            audit_path,
            event_type="capture.committed",
            capture_id=capture_id,
            before_hash=before_hash,
            after_hash=after_hash,
        )
    click.echo(f"Captured {capture_id}")


@cli.group("inbox")
def inbox_command() -> None:
    """Collect and route canonical Inbox captures."""


@inbox_command.command("process")
@click.pass_obj
def process_inbox_command(paths: RuntimePaths) -> None:
    """Identify unprocessed captures and refresh their routing review."""
    result = process_inbox(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
    )
    _echo_inbox_process_result(result)


@inbox_command.command("review")
@click.option("--interactive", is_flag=True)
@click.option(
    "--limit",
    type=click.IntRange(1, 20),
    default=5,
    show_default=True,
    help="Maximum captures to present during interactive review.",
)
@click.pass_obj
def review_inbox_command(
    paths: RuntimePaths,
    interactive: bool,
    limit: int,
) -> None:
    """Refresh and open the Inbox routing review."""
    result = process_inbox(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
    )
    if interactive:
        _review_inbox_interactively(
            paths, review_items(vault_root=paths.vault_root), limit
        )
        result = process_inbox(
            vault_root=paths.vault_root,
            audit_root=paths.audit_root,
        )
    _echo_inbox_process_result(result)
    _open_note(paths, result.review_path)


def _echo_inbox_process_result(result: InboxProcessResult) -> None:
    click.echo(f"Processed captures: {result.processed}.")
    click.echo(f"Needs review: {result.needs_review}.")
    click.echo(f"Routing failures: {result.routing_failures}.")
    click.echo(f"Review: {result.review_path}.")


def _review_inbox_interactively(
    paths: RuntimePaths,
    items: tuple[InboxReviewItem, ...],
    limit: int,
) -> None:
    selected_items = items[:limit]
    if not selected_items:
        click.echo("No captures need review.")
        return
    for index, item in enumerate(selected_items, start=1):
        click.echo("")
        click.echo(f"Capture {index} of {len(selected_items)}")
        click.echo(item.text)
        click.echo(
            f"Suggested: {item.suggested_route} (evidence: {item.evidence_status})"
        )
        if not _review_one_capture(paths, item):
            break


def _review_one_capture(paths: RuntimePaths, item: InboxReviewItem) -> bool:
    while True:
        scope = click.prompt(
            "Choose",
            type=click.Choice(
                ["personal", "work", "archive", "leave", "quit"],
                case_sensitive=False,
            ),
            default=_suggested_scope(item.suggested_route),
            show_choices=True,
        )
        if scope == "quit":
            return False
        if scope == "leave":
            return True
        if scope == "archive":
            _apply_interactive_route(paths, item.capture_id, "archive")
            return True
        if scope == "personal":
            kind = click.prompt(
                "Personal kind",
                type=click.Choice(
                    ["task", "note", "question", "idea", "back"],
                    case_sensitive=False,
                ),
                default=_suggested_kind(item.suggested_route, "personal"),
                show_choices=True,
            )
            if kind == "back":
                continue
            route = {
                "task": "personal-project-task",
                "note": "personal-project-note",
                "question": "personal-project-question",
                "idea": "personal-idea",
            }[kind]
            if _apply_interactive_route(paths, item.capture_id, route):
                return True
            continue
        kind = click.prompt(
            "Work kind",
            type=click.Choice(
                ["task", "note", "question", "idea", "back"],
                case_sensitive=False,
            ),
            default=_suggested_kind(item.suggested_route, "work"),
            show_choices=True,
        )
        if kind == "back":
            continue
        route = {
            "task": "current-work-task",
            "note": "current-work-note",
            "question": "current-work-question",
            "idea": "work-idea",
        }[kind]
        classification = None
        if route == "work-idea":
            classification = click.prompt(
                "Classification",
                type=click.Choice(
                    ["public", "netflix-internal", "netflix-confidential"],
                    case_sensitive=False,
                ),
                show_choices=True,
            )
        if _apply_interactive_route(
            paths,
            item.capture_id,
            route,
            classification=classification,
        ):
            return True


def _apply_interactive_route(
    paths: RuntimePaths,
    capture_id: str,
    route: str,
    *,
    classification: str | None = None,
) -> bool:
    try:
        destination = preview_route(
            vault_root=paths.vault_root,
            route=route,
        )
    except click.ClickException as error:
        click.echo(f"Could not apply route: {error.message}")
        return False
    if route == "archive":
        click.echo("Effect: preserve the capture and mark it archived.")
    else:
        click.echo(f"Destination: {destination}")
    if not click.confirm("Apply this choice?", default=False):
        return False
    try:
        result = route_capture(
            vault_root=paths.vault_root,
            audit_root=paths.audit_root,
            capture_id=capture_id,
            route=route,
            classification=classification,
        )
    except click.ClickException as error:
        click.echo(f"Could not apply route: {error.message}")
        return False
    _echo_inbox_route_result(result, route)
    return True


def _suggested_scope(route: str) -> str:
    if route.startswith("personal-"):
        return "personal"
    if route.startswith("current-work") or route == "work-idea":
        return "work"
    return "leave"


def _suggested_kind(route: str, scope: str) -> str:
    expected = {
        "personal": {
            "personal-project-task": "task",
            "personal-project-note": "note",
            "personal-project-question": "question",
            "personal-idea": "idea",
        },
        "work": {
            "current-work-task": "task",
            "current-work-note": "note",
            "current-work-question": "question",
            "work-idea": "idea",
        },
    }
    return expected[scope].get(route, "back")


@inbox_command.command("route")
@click.argument("capture_id")
@click.option(
    "--to",
    "route",
    required=True,
    type=click.Choice(sorted(ROUTES), case_sensitive=False),
)
@click.option(
    "--classification",
    type=click.Choice(
        ["public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
    help="Required when routing a work idea.",
)
@click.pass_obj
def route_inbox_command(
    paths: RuntimePaths,
    capture_id: str,
    route: str,
    classification: str | None,
) -> None:
    """Route one identified capture to an approved local destination."""
    result = route_capture(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        capture_id=capture_id,
        route=route,
        classification=classification,
    )
    _echo_inbox_route_result(result, route)


def _echo_inbox_route_result(
    result: InboxRouteResult,
    route: str,
) -> None:
    if route == "archive":
        verb = "Already archived" if result.already_routed else "Archived"
        click.echo(f"{verb} {result.capture_id}.")
        return
    verb = "Already routed" if result.already_routed else "Routed"
    click.echo(f"{verb} {result.capture_id} to {result.destination}.")


@cli.command()
@click.pass_obj
def doctor(paths: RuntimePaths) -> None:
    """Verify the minimum local vault structure."""
    missing = [
        str(relative_path)
        for relative_path in REQUIRED_VAULT_FILES
        if not (paths.vault_root / relative_path).is_file()
    ]
    if missing:
        joined = ", ".join(missing)
        raise click.ClickException(f"Missing required vault files: {joined}")

    if (paths.vault_root / "20-work").is_dir():
        missing_work_files = [
            str(relative_path)
            for relative_path in REQUIRED_WORK_FILES
            if not (paths.vault_root / relative_path).is_file()
        ]
        if missing_work_files:
            joined = ", ".join(missing_work_files)
            raise click.ClickException(f"Missing required work files: {joined}")

    core_plugins_path = paths.vault_root / ".obsidian" / "core-plugins.json"
    core_plugins = json.loads(core_plugins_path.read_text(encoding="utf-8"))
    if core_plugins.get("sync") is True:
        raise click.ClickException("Obsidian Sync must be disabled for Kernel v0.")

    click.echo("Healthy: minimum vault structure is present.")


@cli.command()
@click.pass_obj
def start(paths: RuntimePaths) -> None:
    """Open the Edifice home note."""
    _open_note(paths, Path("home.md"))


@cli.command()
@click.pass_obj
def work(paths: RuntimePaths) -> None:
    """Open the active project."""
    _open_note(paths, _current_pointer(paths, "work"))


@cli.command("work-context")
@click.pass_obj
def work_context(paths: RuntimePaths) -> None:
    """Open the local work-context cockpit."""
    _open_note(paths, Path("20-work/home.md"))


@cli.group("meeting")
def meeting_command() -> None:
    """Create human-owned meeting notes."""


@meeting_command.group("series")
def meeting_series_command() -> None:
    """Create and use recurring meeting series."""


@meeting_series_command.command("create")
@click.option("--title", required=True)
@click.option(
    "--scope",
    required=True,
    type=click.Choice(["personal", "work"], case_sensitive=False),
)
@click.option(
    "--classification",
    type=click.Choice(
        ["personal", "public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
)
@click.pass_obj
def create_meeting_series_command(
    paths: RuntimePaths,
    title: str,
    scope: str,
    classification: str | None,
) -> None:
    """Create and open one recurring meeting series."""
    result = create_meeting_series(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        title=title,
        scope=scope,
        classification=classification,
    )
    click.echo(f"Created meeting series: {result.slug}.")
    _open_note(paths, result.note_path)


@meeting_series_command.command("start")
@click.argument("slug")
@click.option(
    "--held-on",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def start_meeting_series_command(
    paths: RuntimePaths,
    slug: str,
    held_on: datetime | None,
) -> None:
    """Create and open one dated meeting in a recurring series."""
    result = start_meeting_series(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        slug=slug,
        meeting_on=held_on.date() if held_on is not None else None,
    )
    click.echo(f"Created meeting note: {result.note_path}.")
    _open_note(paths, result.note_path)


@meeting_command.command("start")
@click.option("--title", required=True)
@click.option(
    "--scope",
    required=True,
    type=click.Choice(["personal", "work"], case_sensitive=False),
)
@click.option(
    "--classification",
    type=click.Choice(
        ["personal", "public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
)
@click.option(
    "--held-on",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def start_meeting_command(
    paths: RuntimePaths,
    title: str,
    scope: str,
    classification: str | None,
    held_on: datetime | None,
) -> None:
    """Create and open one local meeting note."""
    result = create_meeting_note(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        title=title,
        scope=scope,
        classification=classification,
        meeting_on=held_on.date() if held_on is not None else None,
    )
    click.echo(f"Created meeting note: {result.note_path}.")
    _open_note(paths, result.note_path)


@cli.group("task")
def task_command() -> None:
    """Create and operate local work tasks."""


@task_command.command("start")
@click.option("--name", required=True)
@click.option(
    "--classification",
    required=True,
    type=click.Choice(
        ["public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
)
@click.option(
    "--review-on",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.option(
    "--persistence-reason",
    default="Active task state required for the current objective.",
    show_default=True,
)
@click.pass_obj
def start_task_command(
    paths: RuntimePaths,
    name: str,
    classification: str,
    review_on: datetime,
    persistence_reason: str,
) -> None:
    """Create a work task without gathering external context."""
    result = start_work_task(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        name=name,
        classification=classification,
        review_on=review_on.date(),
        persistence_reason=persistence_reason,
    )
    click.echo(f"Created work task: {result.slug}.")
    click.echo(f"Note: {result.note_path}.")
    click.echo("Run `edifice work` to open it.")


@cli.group("review-docs")
def review_docs_command() -> None:
    """Create and operate reusable document-review sessions."""


@review_docs_command.command("start")
@click.option("--name", required=True)
@click.option(
    "--classification",
    required=True,
    type=click.Choice(
        ["public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
)
@click.option(
    "--review-on",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def start_document_review_command(
    paths: RuntimePaths,
    name: str,
    classification: str,
    review_on: datetime,
) -> None:
    """Create a persistent document-review session."""
    slug, review = start_review(
        vault_root=paths.vault_root,
        name=name,
        classification=classification,
        review_on=review_on.date(),
    )
    click.echo(f"Review: {slug}.")
    click.echo(f"Context: {review.context_note.relative_to(paths.vault_root)}.")
    click.echo(f"AI workspace: {review.ai_note.relative_to(paths.vault_root)}.")


@review_docs_command.command("add")
@click.argument("slug")
@click.option("--link", help="Authoritative URL or Markdown link.")
@click.option("--pdf-link", help="Authoritative PDF URL or Markdown link.")
@click.option(
    "--copy-pdf",
    type=(click.Path(path_type=Path, dir_okay=False), str),
    metavar="FILE SOURCE_URL",
)
@click.option("--title", help="Owner-attested document title.")
@click.option("--context", "source_context", help="Why this source matters.")
@click.option("--accept-pdf-name", is_flag=True)
@click.pass_obj
def add_document_review_command(
    paths: RuntimePaths,
    slug: str,
    link: str | None,
    pdf_link: str | None,
    copy_pdf: tuple[Path, str] | None,
    title: str | None,
    source_context: str | None,
    accept_pdf_name: bool,
) -> None:
    """Add one authoritative document to a review session."""
    supplied = sum(value is not None for value in (link, pdf_link, copy_pdf))
    if supplied != 1:
        raise click.ClickException(
            "Provide exactly one of --link, --pdf-link, or --copy-pdf."
        )
    source_url: str
    kind: str
    local_path: str | None = None
    if link is not None:
        source_url, markdown_title = normalize_review_source(link)
        title = title if title is not None else markdown_title
        kind = "link"
    elif pdf_link is not None:
        source_url, markdown_title = normalize_review_source(pdf_link)
        title = title if title is not None else markdown_title
        kind = "pdf-link"
    else:
        assert copy_pdf is not None
        local_file, source_reference = copy_pdf
        source_url, markdown_title = normalize_review_source(source_reference)
        title = title if title is not None else markdown_title
        title, source_context = normalize_review_metadata(
            title=title,
            context=source_context,
        )
        existing_document = find_review_document(
            vault_root=paths.vault_root,
            slug=slug,
            source_url=source_url,
        )
        existing_local_path = (
            existing_document.get("local_path")
            if existing_document is not None
            else None
        )
        if isinstance(existing_local_path, str):
            action, review = add_review_document(
                vault_root=paths.vault_root,
                slug=slug,
                source_url=source_url,
                kind="local-pdf",
                local_path=existing_local_path,
                title=title,
                context=source_context,
            )
            verb = "Updated" if action == "updated" else "Already present"
            click.echo(f"{verb}: {source_url}.")
            click.echo(f"Context: {review.context_note.relative_to(paths.vault_root)}.")
            return
        ensure_review_document_capacity(
            vault_root=paths.vault_root,
            slug=slug,
            source_url=source_url,
        )
        manifest = load_review_manifest(review_paths(paths.vault_root, slug).manifest)
        result = add_pdf(
            vault_root=paths.vault_root,
            audit_root=paths.audit_root,
            source_pdf=local_file,
            scope="work",
            classification=cast(str, manifest["classification"]),
            source_url=source_url,
            document_kind=None,
            title=None,
            creator=None,
            year=None,
            version=None,
            accept_name=accept_pdf_name,
            dry_run=False,
        )
        kind = "local-pdf"
        local_path = result.storage_path.as_posix()
    action, review = add_review_document(
        vault_root=paths.vault_root,
        slug=slug,
        source_url=source_url,
        kind=kind,
        local_path=local_path,
        title=title,
        context=source_context,
    )
    verb = {
        "added": "Added",
        "updated": "Updated",
        "unchanged": "Already present",
    }[action]
    click.echo(f"{verb}: {source_url}.")
    click.echo(f"Context: {review.context_note.relative_to(paths.vault_root)}.")


@review_docs_command.command("gather")
@click.argument("slug")
@click.pass_obj
def gather_document_review_command(paths: RuntimePaths, slug: str) -> None:
    """Read documents and refresh the generated AI analysis."""
    review = gather_review(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        slug=slug,
        codex_binary=os.environ.get("EDIFICE_CODEX_BIN", "codex"),
    )
    click.echo(f"Gathered: {review.ai_note.relative_to(paths.vault_root)}.")


@review_docs_command.command("synthesize")
@click.argument("slug")
@click.pass_obj
def synthesize_document_review_command(paths: RuntimePaths, slug: str) -> None:
    """Publish the latest cross-document synthesis into the context note."""
    review = synthesize_review(vault_root=paths.vault_root, slug=slug)
    click.echo(f"Synthesized: {review.context_note.relative_to(paths.vault_root)}.")


@review_docs_command.command("open")
@click.argument("slug")
@click.pass_obj
def open_document_review_command(paths: RuntimePaths, slug: str) -> None:
    """Open a document-review context note."""
    review = review_paths(paths.vault_root, slug)
    _open_note(paths, review.context_note.relative_to(paths.vault_root))


@review_docs_command.command("status")
@click.argument("slug")
@click.pass_obj
def status_document_review_command(paths: RuntimePaths, slug: str) -> None:
    """Show persistent document-review state."""
    status = get_review_status(vault_root=paths.vault_root, slug=slug)
    click.echo(f"Review: {status.name}")
    click.echo(f"Status: {status.status}")
    click.echo(f"Documents: {status.document_count}")
    click.echo(f"Classification: {status.classification}")
    click.echo(f"Review on: {status.review_on}")
    click.echo(f"Last gathered: {status.last_gathered or 'never'}")


@cli.group("context")
def context_command() -> None:
    """Gather and maintain bounded work context."""


@context_command.command("gather")
@click.option("--jira", "jira_key", required=True, help="JIRA issue key.")
@click.option(
    "--repo",
    "repository",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
    help="Absolute path to the local Git repository.",
)
@click.option(
    "--classification",
    required=True,
    type=click.Choice(
        ["public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
)
@click.option(
    "--review-on",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.option(
    "--persistence-reason",
    default="Active task context required for the current objective.",
    show_default=True,
)
@click.option("--link", "links", multiple=True, help="Manual authoritative link.")
@click.option("--pdf", "pdf_urls", multiple=True, help="Manual PDF link.")
@click.option(
    "--copy-pdf",
    "pdf_copies",
    multiple=True,
    type=(click.Path(path_type=Path, dir_okay=False), str),
    metavar="FILE SOURCE_URL",
    help="Copy one approved local PDF and record its authoritative source.",
)
@click.option(
    "--accept-pdf-name",
    is_flag=True,
    help="Accept medium- or low-confidence names for copied PDFs.",
)
@click.pass_obj
def gather_context(
    paths: RuntimePaths,
    jira_key: str,
    repository: Path,
    classification: str,
    review_on: datetime,
    persistence_reason: str,
    links: tuple[str, ...],
    pdf_urls: tuple[str, ...],
    pdf_copies: tuple[tuple[Path, str], ...],
    accept_pdf_name: bool,
) -> None:
    """Create or refresh one governed work-context note."""
    result = gather_work_context(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        jira_key=jira_key,
        repository=repository,
        classification=classification,
        review_on=review_on.date(),
        persistence_reason=persistence_reason,
        links=links,
        pdf_urls=pdf_urls,
        pdf_copies=pdf_copies,
        accept_pdf_name=accept_pdf_name,
        codex_binary=os.environ.get("EDIFICE_CODEX_BIN", "codex"),
    )
    verb = "Created" if result.created else "Refreshed"
    click.echo(f"{verb} {result.note_path}.")
    click.echo(f"Run report: {result.run_report_path}.")


@cli.group("pdf")
def pdf_command() -> None:
    """Add and verify governed PDF artifacts."""


@pdf_command.command("add")
@click.argument(
    "source_pdf",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.option(
    "--scope",
    required=True,
    type=click.Choice(["personal", "work"], case_sensitive=False),
)
@click.option(
    "--classification",
    required=True,
    type=click.Choice(
        ["personal", "public", "netflix-internal", "netflix-confidential"],
        case_sensitive=False,
    ),
)
@click.option("--source", "source_url", help="Authoritative source URL.")
@click.option(
    "--kind",
    "document_kind",
    type=click.Choice(DOCUMENT_KINDS, case_sensitive=False),
)
@click.option("--title", help="Confirmed document title.")
@click.option("--creator", help="Confirmed author, court, or institution.")
@click.option("--year", type=click.IntRange(1000, 9999))
@click.option("--version", help="Confirmed version, edition, citation, or milestone.")
@click.option(
    "--accept-name",
    is_flag=True,
    help="Accept a medium- or low-confidence proposed filename.",
)
@click.pass_obj
def add_pdf_command(
    paths: RuntimePaths,
    source_pdf: Path,
    scope: str,
    classification: str,
    source_url: str | None,
    document_kind: str | None,
    title: str | None,
    creator: str | None,
    year: int | None,
    version: str | None,
    accept_name: bool,
) -> None:
    """Copy and catalog one intentionally selected PDF."""
    result = add_pdf(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        source_pdf=source_pdf,
        scope=scope,
        classification=classification,
        source_url=source_url,
        document_kind=document_kind,
        title=title,
        creator=creator,
        year=year,
        version=version,
        accept_name=accept_name,
        dry_run=paths.dry_run,
    )
    if result.dry_run:
        click.echo(f"Would add PDF as {result.storage_path}.")
        return
    if result.duplicate:
        click.echo(f"Already cataloged: {result.storage_path}.")
        return
    click.echo(f"Added PDF: {result.storage_path}.")
    click.echo(f"Catalog: {result.catalog_path}.")
    if scope == "personal" and paths.personal_library_root is not None:
        backup = backup_personal_pdfs(
            vault_root=paths.vault_root,
            audit_root=paths.audit_root,
            drive_library_root=paths.personal_library_root,
        )
        click.echo(
            f"Drive library: {backup.copied} copied, {backup.verified} hash-verified."
        )


@pdf_command.command("inventory")
@click.pass_obj
def inventory_pdf_command(paths: RuntimePaths) -> None:
    """Verify cataloged PDFs and identify uncataloged local copies."""
    inventory = inventory_pdfs(paths.vault_root)
    for issue in inventory.issues:
        click.echo(issue)
    click.echo(
        f"{inventory.verified} verified, "
        f"{inventory.unavailable} unavailable, "
        f"{inventory.mismatched} mismatched, "
        f"{inventory.uncataloged} uncataloged"
    )
    if inventory.unavailable or inventory.mismatched or inventory.uncataloged:
        raise click.ClickException("PDF inventory has unresolved items.")


@pdf_command.command("backup-personal")
@click.option(
    "--destination",
    type=click.Path(path_type=Path, file_okay=False),
    help="Override the configured personal Google Drive library.",
)
@click.pass_obj
def backup_personal_pdf_command(
    paths: RuntimePaths,
    destination: Path | None,
) -> None:
    """Copy and verify every personal PDF in the Drive library."""
    drive_library_root = destination or paths.personal_library_root
    if drive_library_root is None:
        raise click.ClickException(
            "Personal library is not configured. Set EDIFICE_PERSONAL_LIBRARY "
            "or pass --destination."
        )
    result = backup_personal_pdfs(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        drive_library_root=drive_library_root,
    )
    click.echo(
        f"Drive library: {result.copied} copied, {result.verified} hash-verified."
    )
    click.echo("Drive sync status: unavailable.")


@pdf_command.group("import-adobe")
def import_adobe_command() -> None:
    """Plan and apply a read-only Adobe PDF migration."""


@import_adobe_command.command("plan")
@click.option(
    "--export-dir",
    type=click.Path(path_type=Path, file_okay=False),
    help="Adobe-downloaded export directory to scan in addition to local cache.",
)
@click.option(
    "--export-complete",
    is_flag=True,
    help="Attest that the export directory contains every Adobe Cloud PDF.",
)
@click.pass_obj
def plan_adobe_command(
    paths: RuntimePaths,
    export_dir: Path | None,
    export_complete: bool,
) -> None:
    """Create a review manifest without importing PDF files."""
    result = plan_adobe_import(
        vault_root=paths.vault_root,
        cache_roots=default_adobe_cache_roots(),
        export_dir=export_dir,
        export_complete=export_complete,
    )
    click.echo(f"Manifest: {result.manifest_path}.")
    click.echo(f"Review: {result.review_path}.")
    click.echo(
        f"Candidates: {result.candidate_count}; "
        f"duplicate source files: {result.duplicate_source_files}."
    )
    click.echo(f"Source completeness: {result.source_completeness}.")


@import_adobe_command.command("apply")
@click.argument(
    "manifest_path",
    type=click.Path(path_type=Path, dir_okay=False),
)
@click.option(
    "--allow-incomplete-source",
    is_flag=True,
    help="Import only PDFs materialized in the local Acrobat cache.",
)
@click.option(
    "--confirm-all-personal",
    is_flag=True,
    help="Confirm every pending candidate belongs in the personal library.",
)
@click.pass_obj
def apply_adobe_command(
    paths: RuntimePaths,
    manifest_path: Path,
    allow_incomplete_source: bool,
    confirm_all_personal: bool,
) -> None:
    """Import approved manifest entries into the personal PDF library."""
    result = apply_adobe_import(
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        manifest_path=manifest_path,
        allow_incomplete_source=allow_incomplete_source,
        confirm_all_personal=confirm_all_personal,
    )
    click.echo(
        f"Imported: {result.imported}; "
        f"already imported: {result.already_imported}; "
        f"skipped: {result.skipped}."
    )
    click.echo(f"Manifest: {result.manifest_path}.")
    if paths.personal_library_root is not None:
        backup = backup_personal_pdfs(
            vault_root=paths.vault_root,
            audit_root=paths.audit_root,
            drive_library_root=paths.personal_library_root,
        )
        click.echo(
            f"Drive library: {backup.copied} copied, {backup.verified} hash-verified."
        )
        click.echo("Drive sync status: unavailable.")


@cli.group("migrate")
def migrate_command() -> None:
    """Inventory, plan, and verify source-preserving migrations."""


@migrate_command.command("inventory")
@click.option(
    "--source",
    "source_kind",
    required=True,
    type=click.Choice(["obsidian", "craft", "coda"], case_sensitive=False),
)
@click.option(
    "--path",
    "source_path",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.pass_obj
def inventory_migration_command(
    paths: RuntimePaths,
    source_kind: str,
    source_path: Path,
) -> None:
    """Create an immutable local snapshot and inventory."""
    migrations_root = _require_migrations_root(paths)
    result = inventory_source_directory(
        source_kind=source_kind,
        source_path=source_path,
        migrations_root=migrations_root,
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
    )
    click.echo(f"Package: {result.package_path}.")
    click.echo(
        f"Snapshot: {result.file_count} files, "
        f"{result.directory_count} directories, {result.total_bytes} bytes."
    )


@migrate_command.command("plan")
@click.argument(
    "package_path",
    type=click.Path(path_type=Path, file_okay=False),
)
@click.pass_obj
def plan_migration_command(paths: RuntimePaths, package_path: Path) -> None:
    """Create review-only content routing proposals."""
    migrations_root = _require_migrations_root(paths)
    result = plan_migration(
        package_path=package_path,
        migrations_root=migrations_root,
        vault_root=paths.vault_root,
    )
    click.echo(f"Planned: {result.package_path}.")
    click.echo(
        f"Mappings: {result.item_count}; Markdown notes: {result.markdown_count}."
    )
    click.echo("Approved mappings: 0.")


@migrate_command.command("approve")
@click.argument(
    "package_path",
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option("--source-prefix", required=True)
@click.option(
    "--route",
    required=True,
    type=click.Choice(["protected-note", "planned"], case_sensitive=False),
)
@click.pass_obj
def approve_migration_command(
    paths: RuntimePaths,
    package_path: Path,
    source_prefix: str,
    route: str,
) -> None:
    """Approve one source-prefix batch against the current mapping hash."""
    migrations_root = _require_migrations_root(paths)
    result = approve_migration_batch(
        package_path=package_path,
        migrations_root=migrations_root,
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
        source_prefix=source_prefix,
        route=route,
    )
    click.echo(
        f"Approved: {result.approved}; already approved: {result.already_approved}."
    )
    click.echo(f"Package: {result.package_path}.")


@migrate_command.command("apply")
@click.argument(
    "package_path",
    type=click.Path(path_type=Path, file_okay=False),
)
@click.pass_obj
def apply_migration_command(paths: RuntimePaths, package_path: Path) -> None:
    """Copy approved mappings into the live vault."""
    migrations_root = _require_migrations_root(paths)
    result = apply_migration(
        package_path=package_path,
        migrations_root=migrations_root,
        vault_root=paths.vault_root,
        audit_root=paths.audit_root,
    )
    click.echo(
        f"Imported: {result.imported}; already imported: {result.already_imported}."
    )
    click.echo(f"Package: {result.package_path}.")


@migrate_command.command("verify")
@click.argument(
    "package_path",
    type=click.Path(path_type=Path, file_okay=False),
)
@click.pass_obj
def verify_migration_command(paths: RuntimePaths, package_path: Path) -> None:
    """Verify immutable raw snapshot bytes."""
    migrations_root = _require_migrations_root(paths)
    result = verify_migration_package(
        package_path=package_path,
        migrations_root=migrations_root,
    )
    for issue in result.issues:
        click.echo(issue)
    click.echo(
        f"{result.verified} verified, "
        f"{result.unavailable} unavailable, "
        f"{result.mismatched} mismatched"
    )
    if result.unavailable or result.mismatched:
        raise click.ClickException("Migration package verification failed.")


@migrate_command.command("status")
@click.pass_obj
def migration_status_command(paths: RuntimePaths) -> None:
    """List local migration packages."""
    migrations_root = _require_migrations_root(paths)
    packages = migration_status(migrations_root)
    if not packages:
        click.echo("No migration packages.")
        return
    for package in packages:
        click.echo(
            f"{package['source']}-{package['profile']}: "
            f"{package['status']} ({package['path']})"
        )


def _require_migrations_root(paths: RuntimePaths) -> Path:
    if paths.migrations_root is None:
        raise click.ClickException(
            "Migration root is not configured. Set EDIFICE_MIGRATIONS_ROOT "
            "or pass --migrations-root."
        )
    return paths.migrations_root


@cli.command()
@click.option(
    "--date",
    "selected_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def today(paths: RuntimePaths, selected_date: datetime | None) -> None:
    """Open a daily review."""
    review_date = (
        selected_date.date()
        if selected_date is not None
        else datetime.now().astimezone().date()
    )
    relative_path = (
        Path("10-personal/operations/reviews/daily") / f"{review_date.isoformat()}.md"
    )
    _open_note(paths, relative_path)


@cli.command()
@click.option(
    "--date",
    "selected_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def review(paths: RuntimePaths, selected_date: datetime | None) -> None:
    """Open the weekly review for a date."""
    review_date = (
        selected_date.date()
        if selected_date is not None
        else datetime.now().astimezone().date()
    )
    week_start = review_date - timedelta(days=review_date.weekday())
    relative_path = (
        Path("10-personal/operations/reviews/weekly")
        / f"{week_start.isoformat()}-weekly.md"
    )
    _open_note(paths, relative_path)


@cli.command()
@click.option(
    "--date",
    "selected_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def status(paths: RuntimePaths, selected_date: datetime | None) -> None:
    """Show the current operating state."""
    status_date = (
        selected_date.date()
        if selected_date is not None
        else datetime.now().astimezone().date()
    )
    week_start = status_date - timedelta(days=status_date.weekday())
    inbox_path = paths.vault_root / "01-inbox" / "inbox.md"
    inbox_count = sum(
        line.startswith("- [ ] ")
        for line in inbox_path.read_text(encoding="utf-8").splitlines()
    )
    work_path = _current_pointer(paths, "work")
    question_path = _current_pointer(paths, "question")
    today_path = (
        Path("10-personal/operations/reviews/daily") / f"{status_date.isoformat()}.md"
    )
    review_path = (
        Path("10-personal/operations/reviews/weekly")
        / f"{week_start.isoformat()}-weekly.md"
    )

    click.echo(f"Vault: {paths.vault_root}")
    click.echo(f"Inbox: {inbox_count} unprocessed")
    click.echo(f"Work: {work_path}")
    click.echo(f"Question: {question_path}")
    click.echo(f"Today: {today_path}")
    click.echo(f"Review: {review_path}")
    click.echo(f"Git: {_git_state(paths.vault_root)}")


def _git_state(vault_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(vault_root), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "unavailable"
    return "changes" if result.stdout.strip() else "clean"


def _current_pointer(paths: RuntimePaths, key: str) -> Path:
    current_path = paths.vault_root / "00-system" / "current.json"
    try:
        current: object = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {current_path}") from error

    if not isinstance(current, dict):
        raise click.ClickException("Current-state pointer must be a JSON object.")

    typed_current = cast(dict[str, object], current)
    value = typed_current.get(key)
    if not isinstance(value, str) or not value:
        raise click.ClickException(f"Current-state pointer is missing: {key}")

    relative_path = Path(value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise click.ClickException(f"Unsafe current-state pointer: {value}")
    return relative_path


def _open_note(paths: RuntimePaths, relative_path: Path) -> None:
    target = paths.vault_root / relative_path
    if not target.is_file():
        raise click.ClickException(f"Vault note does not exist: {relative_path}")

    if paths.dry_run:
        click.echo(f"Would open {relative_path} in Obsidian.")
        return

    query = urlencode(
        {
            "vault": paths.vault_root.name,
            "file": relative_path.as_posix(),
        }
    )
    subprocess.run(["open", f"obsidian://open?{query}"], check=True)
    click.echo(f"Opened {relative_path} in Obsidian.")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _audit_path(audit_root: Path) -> Path:
    audit_root.mkdir(parents=True, exist_ok=True)
    return audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"


@contextmanager
def _capture_lock(audit_root: Path) -> Generator[None]:
    lock_path = audit_root / "capture.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _append_audit_event(
    audit_path: Path,
    *,
    event_type: str,
    capture_id: str,
    before_hash: str,
    after_hash: str,
) -> None:
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "personal",
        "event_type": event_type,
        "capture_id": capture_id,
        "target": "vault://edifice/01-inbox/inbox.md",
        "before_hash": before_hash,
        "after_hash": after_hash,
    }
    encoded = f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode()
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
