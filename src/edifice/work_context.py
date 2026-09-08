import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

import click

from edifice.context_worker import EVIDENCE_STATUSES, gather_with_codex
from edifice.identifiers import new_uuid7

GENERATED_START = "<!-- edifice:generated-context:start -->"
GENERATED_END = "<!-- edifice:generated-context:end -->"
JIRA_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9]+-[1-9][0-9]*$")
SAFE_FILENAME_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PdfCopyRequest:
    source_path: Path
    source_url: str


@dataclass(frozen=True)
class PreparedPdf:
    source_path: Path
    destination_path: Path
    relative_link: str
    source_url: str
    content: bytes
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class GatherResult:
    note_path: Path
    run_report_path: Path
    created: bool


def gather_work_context(
    *,
    vault_root: Path,
    audit_root: Path,
    jira_key: str,
    repository: Path,
    classification: str,
    review_on: date,
    persistence_reason: str,
    links: tuple[str, ...],
    pdf_urls: tuple[str, ...],
    pdf_copies: tuple[tuple[Path, str], ...],
    codex_binary: str,
) -> GatherResult:
    """Gather and persist one bounded, refreshable work-context note."""
    normalized_key = _validate_jira_key(jira_key)
    normalized_repository = _validate_repository(repository)
    normalized_links = tuple(_validate_url(url, "link") for url in links)
    normalized_pdf_urls = tuple(_validate_url(url, "PDF") for url in pdf_urls)
    normalized_persistence_reason = persistence_reason.strip()
    if not normalized_persistence_reason:
        raise click.ClickException("Persistence reason must not be empty.")
    copy_requests = tuple(
        PdfCopyRequest(
            source_path=_validate_pdf_path(source_path),
            source_url=_validate_url(source_url, "PDF source"),
        )
        for source_path, source_url in pdf_copies
    )
    note_relative_path = (
        Path("20-work/operations/projects") / f"{normalized_key.lower()}-context.md"
    )
    note_path = vault_root / note_relative_path
    if note_path.exists():
        _validate_existing_metadata(
            note_path.read_text(encoding="utf-8"),
            jira_key=normalized_key,
            repository=normalized_repository,
            classification=classification,
            review_on=review_on,
            persistence_reason=normalized_persistence_reason,
        )
    context_data = gather_with_codex(
        jira_key=normalized_key,
        repository=normalized_repository,
        codex_binary=codex_binary,
    )
    prepared_pdfs = tuple(
        _prepare_pdf(
            request=request,
            vault_root=vault_root,
            jira_key=normalized_key,
        )
        for request in copy_requests
    )
    generated_section = _render_generated_context(
        context_data=context_data,
        jira_key=normalized_key,
        repository=normalized_repository,
        classification=classification,
        review_on=review_on,
        persistence_reason=normalized_persistence_reason,
    )

    with _context_lock(audit_root, normalized_key):
        created = not note_path.exists()
        before = note_path.read_bytes() if note_path.exists() else b""
        if created:
            note = _new_context_note(
                context_data=context_data,
                jira_key=normalized_key,
                repository=normalized_repository,
                classification=classification,
                review_on=review_on,
                persistence_reason=normalized_persistence_reason,
                generated_section=generated_section,
            )
        else:
            _validate_existing_metadata(
                before.decode("utf-8"),
                jira_key=normalized_key,
                repository=normalized_repository,
                classification=classification,
                review_on=review_on,
                persistence_reason=normalized_persistence_reason,
            )
            note = _replace_generated_context(
                before.decode("utf-8"),
                generated_section,
            )
        note = _append_manual_items(
            note,
            "### Links",
            [_external_link_item(url) for url in normalized_links],
        )
        note = _append_manual_items(
            note,
            "### PDFs",
            [_external_pdf_item(url, classification) for url in normalized_pdf_urls],
        )
        note = _append_manual_items(
            note,
            "### PDFs",
            [_copied_pdf_item(pdf, classification) for pdf in prepared_pdfs],
        )
        after = note.encode("utf-8")

        _preflight_pdf_destinations(prepared_pdfs)
        for prepared_pdf in prepared_pdfs:
            _copy_pdf_without_overwrite(prepared_pdf)
        _replace_atomically(note_path, after)
        run_report_path = _write_run_report(
            vault_root=vault_root,
            jira_key=normalized_key,
            repository=normalized_repository,
            note_relative_path=note_relative_path,
            before=before,
            after=after,
            links=normalized_links,
            pdf_urls=normalized_pdf_urls,
            prepared_pdfs=prepared_pdfs,
        )
        _append_context_audit_event(
            audit_root=audit_root,
            jira_key=normalized_key,
            note_relative_path=note_relative_path,
            before=before,
            after=after,
            prepared_pdfs=prepared_pdfs,
        )

    return GatherResult(
        note_path=note_relative_path,
        run_report_path=run_report_path.relative_to(vault_root),
        created=created,
    )


def _validate_jira_key(value: str) -> str:
    normalized = value.strip().upper()
    if not JIRA_KEY_PATTERN.fullmatch(normalized):
        raise click.ClickException(f"Invalid JIRA key: {value}")
    return normalized


def _validate_repository(repository: Path) -> Path:
    if not repository.is_absolute():
        raise click.ClickException("Repository path must be absolute.")
    resolved = repository.expanduser().resolve()
    if not resolved.is_dir():
        raise click.ClickException(f"Repository does not exist: {repository}")
    result = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise click.ClickException(f"Path is not a Git repository: {repository}")
    return resolved


def _validate_url(value: str, label: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in normalized)
    ):
        raise click.ClickException(f"Invalid {label} URL: {value}")
    return normalized


def _validate_pdf_path(source_path: Path) -> Path:
    if not source_path.is_absolute():
        raise click.ClickException("PDF path must be absolute.")
    resolved = source_path.expanduser().resolve()
    if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
        raise click.ClickException(f"Not a readable PDF file: {source_path}")
    with resolved.open("rb") as source:
        if source.read(5) != b"%PDF-":
            raise click.ClickException(
                f"File does not have a PDF header: {source_path}"
            )
    return resolved


def _prepare_pdf(
    *,
    request: PdfCopyRequest,
    vault_root: Path,
    jira_key: str,
) -> PreparedPdf:
    content = request.source_path.read_bytes()
    filename = _kebab_pdf_filename(request.source_path.stem)
    relative_path = Path("20-work/references/pdfs") / jira_key.lower() / filename
    return PreparedPdf(
        source_path=request.source_path,
        destination_path=vault_root / relative_path,
        relative_link=f"../../references/pdfs/{jira_key.lower()}/{filename}",
        source_url=request.source_url,
        content=content,
        sha256=_sha256(content),
        size_bytes=len(content),
    )


def _kebab_pdf_filename(stem: str) -> str:
    normalized = SAFE_FILENAME_PATTERN.sub("-", stem.lower()).strip("-")
    if not normalized:
        normalized = "document"
    return f"{normalized}.pdf"


def _new_context_note(
    *,
    context_data: dict[str, object],
    jira_key: str,
    repository: Path,
    classification: str,
    review_on: date,
    persistence_reason: str,
    generated_section: str,
) -> str:
    title = _safe_inline(cast(str, context_data["title"]))
    jira_url = f"https://netflix.atlassian.net/browse/{jira_key}"
    created = datetime.now().astimezone().date().isoformat()
    return f"""---
id: work-context-{new_uuid7()}
type: work-context
schema_version: 2
created: {created}
status: active
title: {json.dumps(title)}
classification: {json.dumps(classification)}
authoritative_source: JIRA
external_url: {json.dumps(jira_url)}
jira: {jira_key}
repository: {json.dumps(str(repository))}
review_on: {review_on.isoformat()}
persistence_reason: {json.dumps(persistence_reason)}
---

# {jira_key}: {title}

{generated_section}

## Manual context

### Notes

### Links

### PDFs

### Decisions

### Questions

### Next action
"""


def _replace_generated_context(note: str, generated_section: str) -> str:
    if note.count(GENERATED_START) != 1 or note.count(GENERATED_END) != 1:
        raise click.ClickException(
            "Existing context note has missing or duplicate generated markers."
        )
    start = note.index(GENERATED_START)
    end = note.index(GENERATED_END) + len(GENERATED_END)
    if end <= start:
        raise click.ClickException(
            "Existing context note has invalid generated markers."
        )
    return f"{note[:start]}{generated_section}{note[end:]}"


def _validate_existing_metadata(
    note: str,
    *,
    jira_key: str,
    repository: Path,
    classification: str,
    review_on: date,
    persistence_reason: str,
) -> None:
    metadata = _read_frontmatter(note)
    expected = {
        "jira": jira_key,
        "repository": str(repository),
        "classification": classification,
        "review_on": review_on.isoformat(),
        "persistence_reason": persistence_reason,
    }
    mismatched = [
        key
        for key, expected_value in expected.items()
        if metadata.get(key) != expected_value
    ]
    if mismatched:
        fields = ", ".join(mismatched)
        raise click.ClickException(
            f"Context metadata differs for {fields}. Edit the note metadata manually "
            "before gathering with new values."
        )


def _read_frontmatter(note: str) -> dict[str, str]:
    lines = note.splitlines()
    if not lines or lines[0] != "---":
        raise click.ClickException("Existing context note has no frontmatter.")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise click.ClickException(
            "Existing context note has invalid frontmatter."
        ) from error
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, raw_value = line.partition(":")
        if not separator:
            continue
        value = raw_value.strip()
        if value.startswith('"'):
            try:
                decoded: object = json.loads(value)
            except json.JSONDecodeError as error:
                raise click.ClickException(
                    f"Existing context note has invalid metadata: {key}"
                ) from error
            if not isinstance(decoded, str):
                raise click.ClickException(
                    f"Existing context note has invalid metadata: {key}"
                )
            metadata[key] = decoded
        else:
            metadata[key] = value
    return metadata


def _render_generated_context(
    *,
    context_data: dict[str, object],
    jira_key: str,
    repository: Path,
    classification: str,
    review_on: date,
    persistence_reason: str,
) -> str:
    jira = cast(dict[str, object], context_data["jira"])
    repository_data = cast(dict[str, object], context_data["repository"])
    lines = [
        GENERATED_START,
        "## Generated context",
        "",
        f"- Refreshed: `{datetime.now(UTC).isoformat()}`",
        "- Worker mode: `read-only`",
        "- External mutation: `not-applicable`",
        f"- Classification: `{_safe_code(classification)}`",
        f"- Review on: `{review_on.isoformat()}`",
        f"- Persistence: {_safe_inline(persistence_reason)}",
        "",
        "### JIRA",
        "",
        f"- Issue: [{jira_key}](<{_safe_url(cast(str, jira['url']))}>)",
        f"- Title: {_safe_inline(cast(str, jira['title']))}",
        f"- Status: `{_safe_inline(cast(str, jira['status']))}`",
        f"- Evidence: `{cast(str, jira['evidence_status'])}`",
        f"- Summary: {_safe_inline(cast(str, jira['summary']))}",
        "",
        "### Repository",
        "",
        f"- Path: `{_safe_code(str(repository))}`",
        f"- Revision: `{_safe_code(cast(str, repository_data['revision']))}`",
        f"- Branch: `{_safe_code(cast(str, repository_data['branch']))}`",
        f"- Working tree: `{_safe_code(cast(str, repository_data['working_tree']))}`",
        f"- Evidence: `{cast(str, repository_data['evidence_status'])}`",
        f"- Summary: {_safe_inline(cast(str, repository_data['summary']))}",
        "",
        "### Verified context",
        "",
    ]
    lines.extend(
        _fact_lines(
            cast(list[object], context_data["facts"]), empty="No facts returned."
        )
    )
    lines.extend(["", "### Relevant code", ""])
    relevant_files = cast(list[object], context_data["relevant_files"])
    if relevant_files:
        for item in relevant_files:
            typed = cast(dict[str, object], item)
            lines.append(
                f"- `{_safe_code(cast(str, typed['path']))}`: "
                f"{_safe_inline(cast(str, typed['reason']))} "
                f"[`{cast(str, typed['evidence_status'])}`]"
            )
    else:
        lines.append("- No relevant files returned.")
    lines.extend(["", "### Authoritative links", ""])
    sources = cast(list[object], context_data["sources"])
    if sources:
        for item in sources:
            typed = cast(dict[str, object], item)
            lines.append(
                f"- [{_safe_inline(cast(str, typed['label']))}]"
                f"(<{_safe_url(cast(str, typed['url']))}>) "
                f"({_safe_inline(cast(str, typed['kind']))}, "
                f"`{cast(str, typed['evidence_status'])}`)"
            )
    else:
        lines.append("- No authoritative links returned.")
    lines.extend(["", "### Blockers", ""])
    lines.extend(
        _fact_lines(
            cast(list[object], context_data["blockers"]),
            empty="No blockers returned.",
        )
    )
    lines.extend(["", "### Open questions", ""])
    lines.extend(
        _string_lines(
            cast(list[object], context_data["questions"]),
            empty="No open questions returned.",
        )
    )
    lines.extend(["", "### Suggested next actions", ""])
    lines.extend(
        _string_lines(
            cast(list[object], context_data["next_actions"]),
            empty="No next actions returned.",
        )
    )
    lines.extend(["", GENERATED_END])
    return "\n".join(lines)


def _fact_lines(items: list[object], *, empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    lines: list[str] = []
    for item in items:
        typed = cast(dict[str, object], item)
        status = cast(str, typed["evidence_status"])
        if status not in EVIDENCE_STATUSES:
            raise click.ClickException(f"Invalid evidence status: {status}")
        lines.append(
            f"- {_safe_inline(cast(str, typed['text']))} "
            f"(source: {_safe_inline(cast(str, typed['source']))}; "
            f"evidence: `{status}`)"
        )
    return lines


def _string_lines(items: list[object], *, empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    return [f"- {_safe_inline(cast(str, item))}" for item in items]


def _append_manual_items(note: str, heading: str, items: Iterable[str]) -> str:
    additions = [item for item in items if item and item not in note]
    if not additions:
        return note
    lines = note.splitlines()
    try:
        heading_index = lines.index(heading)
    except ValueError as error:
        raise click.ClickException(
            f"Manual context section is missing: {heading}"
        ) from error
    insertion_index = len(lines)
    for index in range(heading_index + 1, len(lines)):
        if lines[index].startswith("### ") or lines[index].startswith("## "):
            insertion_index = index
            break
    while insertion_index > heading_index + 1 and lines[insertion_index - 1] == "":
        insertion_index -= 1
    new_lines = [*lines[:insertion_index]]
    if new_lines and new_lines[-1] != "":
        new_lines.append("")
    new_lines.extend(additions)
    new_lines.extend(["", *lines[insertion_index:]])
    return "\n".join(new_lines).rstrip() + "\n"


def _external_link_item(url: str) -> str:
    return f"- [{_url_label(url)}](<{url}>)"


def _external_pdf_item(url: str, classification: str) -> str:
    return (
        f"- [{_url_label(url)}](<{url}>)\n"
        f"  - source: authoritative link\n"
        f"  - classification: `{_safe_code(classification)}`\n"
        f"  - verification: `owner-attested`"
    )


def _copied_pdf_item(pdf: PreparedPdf, classification: str) -> str:
    return (
        f"- [{_safe_inline(pdf.destination_path.name)}]"
        f"(<{pdf.relative_link}>)\n"
        f"  - source: [authoritative PDF](<{pdf.source_url}>)\n"
        f"  - classification: `{_safe_code(classification)}`\n"
        f"  - sha256: `{pdf.sha256}`\n"
        f"  - size_bytes: `{pdf.size_bytes}`\n"
        f"  - verification: `hash-match`"
    )


def _url_label(url: str) -> str:
    parsed = urlparse(url)
    filename = unquote(Path(parsed.path).name)
    return _safe_inline(filename or parsed.netloc)


def _safe_inline(value: str) -> str:
    return " ".join(
        value.replace(GENERATED_START, "")
        .replace(GENERATED_END, "")
        .replace("<!--", "&lt;!--")
        .replace("-->", "--&gt;")
        .split()
    )


def _safe_code(value: str) -> str:
    return _safe_inline(value).replace("`", "'")


def _safe_url(value: str) -> str:
    return value.replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")


def _preflight_pdf_destinations(prepared_pdfs: tuple[PreparedPdf, ...]) -> None:
    seen_destinations: set[Path] = set()
    for pdf in prepared_pdfs:
        if pdf.destination_path in seen_destinations:
            raise click.ClickException(
                f"Duplicate PDF destination: {pdf.destination_path.name}"
            )
        seen_destinations.add(pdf.destination_path)
        if not pdf.destination_path.exists():
            continue
        existing_hash = _sha256(pdf.destination_path.read_bytes())
        if existing_hash != pdf.sha256:
            raise click.ClickException(
                f"Refusing to overwrite a different PDF: {pdf.destination_path}"
            )


def _copy_pdf_without_overwrite(pdf: PreparedPdf) -> None:
    if pdf.destination_path.exists():
        return
    pdf.destination_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=pdf.destination_path.parent,
        prefix=f".{pdf.destination_path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(pdf.content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.link(temporary_path, pdf.destination_path)
    except FileExistsError:
        existing_hash = _sha256(pdf.destination_path.read_bytes())
        if existing_hash != pdf.sha256:
            raise click.ClickException(
                f"Refusing to overwrite a different PDF: {pdf.destination_path}"
            ) from None
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_run_report(
    *,
    vault_root: Path,
    jira_key: str,
    repository: Path,
    note_relative_path: Path,
    before: bytes,
    after: bytes,
    links: tuple[str, ...],
    pdf_urls: tuple[str, ...],
    prepared_pdfs: tuple[PreparedPdf, ...],
) -> Path:
    timestamp = datetime.now(UTC)
    report_path = (
        vault_root
        / "20-work"
        / "run-reports"
        / (
            f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-"
            f"{jira_key.lower()}-{str(new_uuid7())[:8]}.md"
        )
    )
    copied_pdf_lines = (
        "\n".join(
            f"- `{pdf.destination_path.relative_to(vault_root)}`: `{pdf.sha256}`"
            for pdf in prepared_pdfs
        )
        or "- None."
    )
    report = f"""---
type: work-context-run-report
created: {timestamp.date().isoformat()}
jira: {jira_key}
---

# Context gather: {jira_key}

- Timestamp: `{timestamp.isoformat()}`
- Repository: `{_safe_code(str(repository))}`
- Context note: `vault://edifice/{note_relative_path.as_posix()}`
- Before: `{_sha256(before)}`
- After: `{_sha256(after)}`
- Worker sandbox: `read-only`
- External mutation: `not-applicable`
- Knowledge tool: `core-tools.nusdgs_search_knowledge_base`
- Manual links supplied: `{len(links)}`
- PDF links supplied: `{len(pdf_urls)}`

## Copied PDFs

{copied_pdf_lines}
"""
    _replace_atomically(report_path, report.encode("utf-8"))
    return report_path


def _append_context_audit_event(
    *,
    audit_root: Path,
    jira_key: str,
    note_relative_path: Path,
    before: bytes,
    after: bytes,
    prepared_pdfs: tuple[PreparedPdf, ...],
) -> None:
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_path = audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "work",
        "event_type": "context.gathered",
        "jira": jira_key,
        "target": f"vault://edifice/{note_relative_path.as_posix()}",
        "before_hash": _sha256(before),
        "after_hash": _sha256(after),
        "copied_pdf_hashes": [pdf.sha256 for pdf in prepared_pdfs],
        "worker_sandbox": "read-only",
        "external_mutation": False,
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
        if target.exists():
            temporary_path.chmod(target.stat().st_mode)
        else:
            temporary_path.chmod(0o600)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


@contextmanager
def _context_lock(audit_root: Path, jira_key: str) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / f"context-{jira_key.lower()}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
