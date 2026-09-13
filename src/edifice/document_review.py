import hashlib
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import unquote, urlparse

import click

from edifice.context_worker import EVIDENCE_STATUSES
from edifice.document_review_worker import (
    gather_document_review,
    validate_document_review,
    validate_document_review_subject,
)
from edifice.identifiers import new_uuid7

SOURCES_START = "<!-- edifice:document-review-sources:start -->"
SOURCES_END = "<!-- edifice:document-review-sources:end -->"
SYNTHESIS_START = "<!-- edifice:document-review-synthesis:start -->"
SYNTHESIS_END = "<!-- edifice:document-review-synthesis:end -->"
ANALYSIS_START = "<!-- edifice:document-review-analysis:start -->"
ANALYSIS_END = "<!-- edifice:document-review-analysis:end -->"
CLASSIFICATIONS = {"public", "netflix-internal", "netflix-confidential"}
DOCUMENT_KINDS = {
    "google-doc",
    "google-drive-file",
    "google-form",
    "google-sheet",
    "google-slides",
    "link",
    "local-pdf",
    "pdf-link",
    "web-link",
}
REVIEW_STATUSES = {"active", "gathered", "synthesized"}
MAX_DOCUMENTS = 20
MARKDOWN_LINK = re.compile(
    r"^\[([^\]]+)\]\((?:<([^>]+)>|([^\s)]+))\)$",
)


@dataclass(frozen=True)
class ReviewPaths:
    manifest: Path
    latest: Path
    context_note: Path
    ai_note: Path


@dataclass(frozen=True)
class ReviewStatus:
    name: str
    status: str
    document_count: int
    classification: str
    review_on: str
    last_gathered: str | None


def start_review(
    *,
    vault_root: Path,
    name: str,
    classification: str,
    review_on: date,
) -> tuple[str, ReviewPaths]:
    """Create one persistent document-review session."""
    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise click.ClickException("Review name must not be empty.")
    slug = _slug(normalized_name)
    paths = review_paths(vault_root, slug)
    if any(
        path.exists() for path in (paths.manifest, paths.context_note, paths.ai_note)
    ):
        raise click.ClickException(f"Document review already exists: {slug}")
    now = datetime.now(UTC)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "review_id": f"document-review-{new_uuid7()}",
        "slug": slug,
        "name": normalized_name,
        "classification": classification,
        "review_on": review_on.isoformat(),
        "status": "active",
        "created_at": now.isoformat(),
        "last_gathered": None,
        "gathered_manifest_hash": None,
        "documents": [],
    }
    manifest_bytes = _json_bytes(manifest)
    context_bytes = _new_context_note(manifest).encode()
    ai_bytes = _new_ai_note(manifest).encode()
    try:
        _write_new_atomically(paths.manifest, manifest_bytes)
        _write_new_atomically(paths.context_note, context_bytes)
        _write_new_atomically(paths.ai_note, ai_bytes)
    except Exception:
        _remove_unchanged_file(paths.ai_note, ai_bytes)
        _remove_unchanged_file(paths.context_note, context_bytes)
        _remove_unchanged_file(paths.manifest, manifest_bytes)
        raise
    return slug, paths


def add_review_document(
    *,
    vault_root: Path,
    slug: str,
    source_url: str,
    kind: str,
    local_path: str | None = None,
    title: str | None = None,
    context: str | None = None,
) -> tuple[str, ReviewPaths]:
    """Add one authoritative source to a persistent review session."""
    paths = review_paths(vault_root, _validate_slug(slug))
    manifest = load_review_manifest(paths.manifest)
    url, markdown_title = normalize_review_source(source_url)
    normalized_title, normalized_context = normalize_review_metadata(
        title=title if title is not None else markdown_title,
        context=context,
    )
    documents = cast(list[object], manifest["documents"])
    for item in documents:
        document = cast(dict[str, object], item)
        if document.get("source_url") != url:
            continue
        changed = _update_owner_metadata(
            document,
            title=normalized_title,
            context=normalized_context,
        )
        if local_path is not None:
            detected_kind = _detect_document_kind(
                url,
                kind=kind,
                local_path=local_path,
            )
            if (
                document.get("kind") != detected_kind
                or document.get("local_path") != local_path
            ):
                document["kind"] = detected_kind
                document["local_path"] = local_path
                changed = True
        _validate_manifest_document(document, paths.manifest)
        if changed:
            manifest["status"] = "active"
        _write_json(paths.manifest, manifest)
        _replace_section(
            paths.context_note,
            SOURCES_START,
            SOURCES_END,
            _render_sources(documents),
        )
        return ("updated" if changed else "unchanged"), paths
    if len(documents) >= MAX_DOCUMENTS:
        raise click.ClickException(
            f"Document reviews support at most {MAX_DOCUMENTS} documents."
        )
    detected_kind = _detect_document_kind(url, kind=kind, local_path=local_path)
    document = {
        "document_id": f"document-{len(documents) + 1}",
        "kind": detected_kind,
        "source_url": url,
        "local_path": local_path,
        "label": normalized_title or _url_label(url, detected_kind),
        "title": normalized_title,
        "context": normalized_context,
        "evidence_status": "owner-attested",
    }
    _validate_manifest_document(document, paths.manifest)
    documents.append(document)
    manifest["status"] = "active"
    _write_json(paths.manifest, manifest)
    _replace_section(
        paths.context_note,
        SOURCES_START,
        SOURCES_END,
        _render_sources(documents),
    )
    return "added", paths


def review_contains_document(
    *,
    vault_root: Path,
    slug: str,
    source_url: str,
) -> bool:
    """Return whether a review already contains an authoritative source."""
    return (
        find_review_document(
            vault_root=vault_root,
            slug=slug,
            source_url=source_url,
        )
        is not None
    )


def find_review_document(
    *,
    vault_root: Path,
    slug: str,
    source_url: str,
) -> dict[str, object] | None:
    """Return the registered document for an authoritative source URL."""
    paths = review_paths(vault_root, _validate_slug(slug))
    manifest = load_review_manifest(paths.manifest)
    url, _ = normalize_review_source(source_url)
    documents = cast(list[dict[str, object]], manifest["documents"])
    return next(
        (document for document in documents if document["source_url"] == url),
        None,
    )


def normalize_review_source(value: str) -> tuple[str, str | None]:
    """Normalize a raw or Markdown-formatted document link."""
    normalized = value.strip()
    match = MARKDOWN_LINK.fullmatch(normalized)
    if match is None:
        return _validate_url(normalized), None
    label = _unescape_markdown_label(match.group(1))
    url = _validate_url(match.group(2) or match.group(3))
    if _looks_like_url(label):
        return url, None
    return url, _normalize_optional_text(
        label,
        field="Markdown link label",
        max_length=240,
    )


def normalize_review_metadata(
    *,
    title: str | None,
    context: str | None,
) -> tuple[str | None, str | None]:
    """Normalize owner-provided review metadata before any dependent write."""
    return (
        _normalize_optional_text(
            title,
            field="Document title",
            max_length=240,
        ),
        _normalize_optional_text(
            context,
            field="Document context",
            max_length=2000,
        ),
    )


def gather_review(
    *,
    vault_root: Path,
    audit_root: Path,
    slug: str,
    codex_binary: str,
) -> ReviewPaths:
    """Gather and persist read-only per-document analysis."""
    paths = review_paths(vault_root, _validate_slug(slug))
    manifest = load_review_manifest(paths.manifest)
    documents = cast(list[dict[str, object]], manifest["documents"])
    _validate_local_pdf_boundaries(vault_root, documents)
    review = gather_document_review(
        review_name=cast(str, manifest["name"]),
        documents=documents,
        vault_root=vault_root,
        codex_binary=codex_binary,
    )
    _write_json(paths.latest, review)
    _replace_section(
        paths.ai_note,
        ANALYSIS_START,
        ANALYSIS_END,
        _render_analysis(review),
    )
    _replace_section(
        paths.context_note,
        SOURCES_START,
        SOURCES_END,
        _render_sources(documents, review),
    )
    now = datetime.now(UTC)
    manifest["last_gathered"] = now.isoformat()
    manifest["gathered_manifest_hash"] = _analysis_basis_hash(manifest)
    manifest["status"] = "gathered"
    _write_json(paths.manifest, manifest)
    _write_run_report(
        vault_root=vault_root,
        slug=cast(str, manifest["slug"]),
        review=review,
        gathered_at=now,
    )
    _append_audit(
        audit_root=audit_root,
        event_type="document-review.gathered",
        review_id=cast(str, manifest["review_id"]),
        document_count=len(documents),
    )
    return paths


def synthesize_review(*, vault_root: Path, slug: str) -> ReviewPaths:
    """Publish the latest cross-document synthesis into the context note."""
    paths = review_paths(vault_root, _validate_slug(slug))
    if not paths.latest.is_file():
        raise click.ClickException("Gather the document review before synthesizing.")
    manifest = load_review_manifest(paths.manifest)
    if manifest["gathered_manifest_hash"] != _analysis_basis_hash(manifest):
        raise click.ClickException(
            "Document review changed after the latest gather. Gather again before "
            "synthesizing."
        )
    review = load_review_result(paths.latest)
    validate_document_review_subject(
        review,
        cast(str, manifest["name"]),
        cast(list[dict[str, object]], manifest["documents"]),
    )
    _replace_section(
        paths.context_note,
        SYNTHESIS_START,
        SYNTHESIS_END,
        _render_synthesis(review),
    )
    manifest["status"] = "synthesized"
    _write_json(paths.manifest, manifest)
    return paths


def get_review_status(*, vault_root: Path, slug: str) -> ReviewStatus:
    """Read persistent review state."""
    paths = review_paths(vault_root, _validate_slug(slug))
    manifest = load_review_manifest(paths.manifest)
    documents = cast(list[object], manifest["documents"])
    return ReviewStatus(
        name=cast(str, manifest["name"]),
        status=cast(str, manifest["status"]),
        document_count=len(documents),
        classification=cast(str, manifest["classification"]),
        review_on=cast(str, manifest["review_on"]),
        last_gathered=cast(str | None, manifest["last_gathered"]),
    )


def load_review_manifest(path: Path) -> dict[str, object]:
    """Load and validate one review manifest."""
    manifest = _load_json(path)
    manifest.setdefault("gathered_manifest_hash", None)
    required = {
        "schema_version",
        "review_id",
        "slug",
        "name",
        "classification",
        "review_on",
        "status",
        "created_at",
        "last_gathered",
        "gathered_manifest_hash",
        "documents",
    }
    if set(manifest) != required or manifest.get("schema_version") != 1:
        raise click.ClickException(f"Invalid document-review manifest: {path}")
    if (
        not isinstance(manifest.get("review_id"), str)
        or not isinstance(manifest.get("slug"), str)
        or not isinstance(manifest.get("name"), str)
        or not isinstance(manifest.get("classification"), str)
        or not isinstance(manifest.get("review_on"), str)
        or not isinstance(manifest.get("created_at"), str)
        or manifest.get("last_gathered") is not None
        and not isinstance(manifest.get("last_gathered"), str)
        or manifest.get("gathered_manifest_hash") is not None
        and not isinstance(manifest.get("gathered_manifest_hash"), str)
    ):
        raise click.ClickException(f"Invalid document-review manifest: {path}")
    if (
        manifest["classification"] not in CLASSIFICATIONS
        or manifest["status"] not in REVIEW_STATUSES
        or _validate_slug(cast(str, manifest["slug"])) != path.stem
    ):
        raise click.ClickException(f"Invalid document-review manifest: {path}")
    documents = manifest.get("documents")
    if not isinstance(documents, list):
        raise click.ClickException(f"Invalid document-review manifest: {path}")
    typed_documents = cast(list[object], documents)
    if len(typed_documents) > MAX_DOCUMENTS:
        raise click.ClickException(f"Invalid document-review manifest: {path}")
    source_urls: set[str] = set()
    document_ids: set[str] = set()
    for item in typed_documents:
        _validate_manifest_document(item, path)
        document = cast(dict[str, object], item)
        source_url = cast(str, document["source_url"])
        document_id = cast(str, document["document_id"])
        if source_url in source_urls or document_id in document_ids:
            raise click.ClickException(f"Invalid document-review manifest: {path}")
        source_urls.add(source_url)
        document_ids.add(document_id)
    return manifest


def load_review_result(path: Path) -> dict[str, object]:
    """Load the worker result used for deterministic synthesis."""
    return validate_document_review(_load_json(path))


def review_paths(vault_root: Path, slug: str) -> ReviewPaths:
    slug = _validate_slug(slug)
    base = vault_root / "20-work" / "references" / "document-reviews"
    return ReviewPaths(
        manifest=base / f"{slug}.json",
        latest=base / f"{slug}-latest.json",
        context_note=(
            vault_root
            / "20-work"
            / "operations"
            / "projects"
            / f"{slug}-document-review.md"
        ),
        ai_note=vault_root / "20-work" / "ai" / f"{slug}-document-review.md",
    )


def _new_context_note(manifest: dict[str, object]) -> str:
    return f"""---
id: {manifest["review_id"]}
type: document-review
schema_version: 1
created: {datetime.now(UTC).date().isoformat()}
status: active
classification: {manifest["classification"]}
review_on: {manifest["review_on"]}
---

# {manifest["name"]}

{SOURCES_START}
## Documents

No documents added.
{SOURCES_END}

{SYNTHESIS_START}
## Current synthesis

Run `edifice review-docs gather` and `synthesize`.
{SYNTHESIS_END}

## Manual context

### Objective

### Review criteria

### Notes

### Questions

### Feedback draft

### Next action
"""


def _new_ai_note(manifest: dict[str, object]) -> str:
    return f"""---
type: document-review-ai
schema_version: 1
created: {datetime.now(UTC).date().isoformat()}
review_id: {manifest["review_id"]}
---

# {manifest["name"]}: AI review

{ANALYSIS_START}
## Generated analysis

Run `edifice review-docs gather`.
{ANALYSIS_END}

## Manual analyst notes

"""


def _render_sources(
    documents: Sequence[object],
    review: dict[str, object] | None = None,
) -> str:
    lines = ["## Documents", ""]
    reviewed_documents = _reviewed_documents_by_id(review)
    for item in documents:
        document = cast(dict[str, object], item)
        reviewed = reviewed_documents.get(cast(str, document["document_id"]))
        owner_title = document.get("title")
        verified_title = reviewed.get("title") if reviewed is not None else None
        label = _safe_inline(
            cast(
                str,
                owner_title
                if isinstance(owner_title, str)
                else verified_title
                if isinstance(verified_title, str)
                else document["label"],
            )
        )
        url = cast(str, document["source_url"])
        evidence_status = (
            "owner-attested"
            if isinstance(owner_title, str)
            else reviewed["evidence_status"]
            if reviewed is not None
            else document["evidence_status"]
        )
        lines.append(
            f"- [{label}](<{url}>) (`{document['kind']}`, `{evidence_status}`)"
        )
        source_context = document.get("context")
        if isinstance(source_context, str):
            lines.append(
                f"  - Context: {_safe_inline(source_context)} (`owner-attested`)"
            )
        local_path = document.get("local_path")
        if isinstance(local_path, str):
            lines.append(f"  - Local: `{_safe_code(local_path)}`")
        if reviewed is not None:
            if (
                isinstance(owner_title, str)
                and isinstance(verified_title, str)
                and verified_title != owner_title
            ):
                lines.append(
                    f"  - Verified title: {_safe_inline(verified_title)} "
                    f"(`{reviewed['evidence_status']}`)"
                )
            lines.append(
                f"  - Purpose: {_truncate_inline(cast(str, reviewed['purpose']), 300)}"
            )
            lines.append(
                f"  - Summary: {_truncate_inline(cast(str, reviewed['summary']), 500)}"
            )
    return "\n".join(lines)


def _render_analysis(review: dict[str, object]) -> str:
    lines = ["## Generated analysis", ""]
    for value in cast(list[object], review["documents"]):
        document = cast(dict[str, object], value)
        lines.extend(
            [
                f"### {_safe_inline(cast(str, document['title']))}",
                "",
                (
                    f"- Source: "
                    f"[{_safe_inline(cast(str, document['document_id']))}]"
                    f"(<{document['source_url']}>)"
                ),
                f"- Evidence: `{document['evidence_status']}`",
                f"- Purpose: {_safe_inline(cast(str, document['purpose']))}",
                f"- Summary: {_safe_inline(cast(str, document['summary']))}",
                "",
                "#### Key claims",
                "",
            ]
        )
        claims = cast(list[object], document["key_claims"])
        lines.extend(
            f"- {_safe_inline(cast(str, cast(dict[str, object], claim)['text']))} "
            f"(`{cast(dict[str, object], claim)['evidence_status']}`)"
            for claim in claims
        )
        for heading, key in (
            ("Strengths", "strengths"),
            ("Concerns", "concerns"),
            ("Questions", "questions"),
            ("Proposed feedback", "proposed_feedback"),
        ):
            lines.extend(["", f"#### {heading}", ""])
            lines.extend(_bullet_lines(cast(list[object], document[key])))
        lines.append("")
    lines.extend(["## Cross-document synthesis", ""])
    cross = cast(dict[str, object], review["cross_document"])
    lines.append(f"- Summary: {_safe_inline(cast(str, cross['summary']))}")
    for heading, key in (
        ("Agreements", "agreements"),
        ("Conflicts", "conflicts"),
        ("Gaps", "gaps"),
        ("Decision points", "decision_points"),
        ("Combined feedback", "proposed_feedback"),
    ):
        lines.extend(["", f"### {heading}", ""])
        lines.extend(_bullet_lines(cast(list[object], cross[key])))
    lines.extend(["", "## Limitations", ""])
    lines.extend(_bullet_lines(cast(list[object], review["limitations"])))
    return "\n".join(lines)


def _render_synthesis(review: dict[str, object]) -> str:
    cross = cast(dict[str, object], review["cross_document"])
    lines = [
        "## Current synthesis",
        "",
        _safe_inline(cast(str, cross["summary"])),
    ]
    for heading, key in (
        ("Agreements", "agreements"),
        ("Conflicts", "conflicts"),
        ("Gaps", "gaps"),
        ("Decision points", "decision_points"),
        ("Proposed feedback", "proposed_feedback"),
    ):
        lines.extend(["", f"### {heading}", ""])
        lines.extend(_bullet_lines(cast(list[object], cross[key])))
    return "\n".join(lines)


def _bullet_lines(items: list[object]) -> list[str]:
    return [f"- {_safe_inline(cast(str, item))}" for item in items] or ["- None."]


def _replace_section(path: Path, start_marker: str, end_marker: str, body: str) -> None:
    content = path.read_text(encoding="utf-8")
    if content.count(start_marker) != 1 or content.count(end_marker) != 1:
        raise click.ClickException(f"Invalid generated markers in {path}")
    start = content.index(start_marker) + len(start_marker)
    end = content.index(end_marker)
    if end < start:
        raise click.ClickException(f"Invalid generated markers in {path}")
    updated = f"{content[:start]}\n{body}\n{content[end:]}"
    _replace_atomically(path, updated.encode())


def _write_run_report(
    *,
    vault_root: Path,
    slug: str,
    review: dict[str, object],
    gathered_at: datetime,
) -> None:
    path = (
        vault_root
        / "20-work"
        / "run-reports"
        / (
            f"{gathered_at.strftime('%Y-%m-%d-%H%M%S')}-{slug}-"
            f"document-review-{new_uuid7()}.md"
        )
    )
    report = f"""---
type: document-review-run-report
created: {gathered_at.date().isoformat()}
---

# Document review gather: {slug}

- Documents: `{len(cast(list[object], review["documents"]))}`
- Worker: `read-only`
- External mutation: `not-applicable`
- Result: `vault://edifice/20-work/references/document-reviews/{slug}-latest.json`
"""
    _replace_atomically(path, report.encode())


def _append_audit(
    *,
    audit_root: Path,
    event_type: str,
    review_id: str,
    document_count: int,
) -> None:
    audit_root.mkdir(parents=True, exist_ok=True)
    path = audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "work",
        "event_type": event_type,
        "review_id": review_id,
        "document_count": document_count,
        "external_mutation": False,
    }
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(
            descriptor,
            f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode(),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not slug:
        raise click.ClickException("Review name does not produce a safe slug.")
    return slug


def _validate_slug(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise click.ClickException(f"Invalid document-review slug: {value}")
    return value


def _validate_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in normalized)
        or "<" in normalized
        or ">" in normalized
    ):
        raise click.ClickException(f"Invalid document URL: {value}")
    return normalized


def _validate_manifest_document(value: object, manifest_path: Path) -> None:
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")
    document = cast(dict[str, object], value)
    required = {
        "document_id",
        "kind",
        "source_url",
        "local_path",
        "label",
        "evidence_status",
    }
    optional = {"title", "context"}
    if not required.issubset(document) or not set(document).issubset(
        required | optional
    ):
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")
    document.setdefault("title", None)
    document.setdefault("context", None)
    if (
        not isinstance(document.get("document_id"), str)
        or not isinstance(document.get("kind"), str)
        or not isinstance(document.get("source_url"), str)
        or not isinstance(document.get("label"), str)
        or document.get("evidence_status") not in EVIDENCE_STATUSES
    ):
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")
    title = document.get("title")
    context = document.get("context")
    if title is not None and not isinstance(title, str):
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")
    if context is not None and not isinstance(context, str):
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")
    normalized_title = _normalize_optional_text(
        title,
        field="Document title",
        max_length=240,
    )
    normalized_context = _normalize_optional_text(
        context,
        field="Document context",
        max_length=2000,
    )
    source_url = _validate_url(cast(str, document["source_url"]))
    original_kind = cast(str, document["kind"])
    if original_kind not in DOCUMENT_KINDS:
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")
    kind = _detect_document_kind(
        source_url,
        kind=original_kind,
        local_path=cast(str | None, document["local_path"]),
    )
    document["kind"] = kind
    document["title"] = normalized_title
    document["context"] = normalized_context
    document["label"] = normalized_title or _url_label(source_url, kind)
    local_path = document["local_path"]
    if kind == "local-pdf":
        _validate_local_pdf_path(local_path, manifest_path)
    elif local_path is not None:
        raise click.ClickException(f"Invalid document-review manifest: {manifest_path}")


def _validate_local_pdf_path(value: object, manifest_path: Path) -> None:
    if not isinstance(value, str) or "\\" in value:
        raise click.ClickException(f"Invalid local PDF path in {manifest_path}")
    path = PurePosixPath(value)
    allowed_root = PurePosixPath("20-work/references/pdfs")
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.suffix.casefold() != ".pdf"
        or path.parts[: len(allowed_root.parts)] != allowed_root.parts
    ):
        raise click.ClickException(f"Invalid local PDF path in {manifest_path}")


def _validate_local_pdf_boundaries(
    vault_root: Path,
    documents: list[dict[str, object]],
) -> None:
    allowed_root = (vault_root / "20-work" / "references" / "pdfs").resolve()
    for document in documents:
        local_path = document["local_path"]
        if not isinstance(local_path, str):
            continue
        resolved = (vault_root / local_path).resolve()
        if not resolved.is_relative_to(allowed_root):
            raise click.ClickException(
                f"Local PDF resolves outside the governed work library: {local_path}"
            )


def _detect_document_kind(url: str, *, kind: str, local_path: str | None) -> str:
    if local_path is not None or kind == "local-pdf":
        return "local-pdf"
    if kind == "pdf-link":
        return "pdf-link"
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    if host == "docs.google.com":
        google_kinds = {
            "/document/": "google-doc",
            "/forms/": "google-form",
            "/presentation/": "google-slides",
            "/spreadsheets/": "google-sheet",
        }
        for prefix, detected_kind in google_kinds.items():
            if path.startswith(prefix):
                return detected_kind
    if host == "drive.google.com":
        return "google-drive-file"
    if path.endswith(".pdf"):
        return "pdf-link"
    return "web-link"


def _url_label(url: str, kind: str) -> str:
    kind_labels = {
        "google-doc": "Google Doc",
        "google-drive-file": "Google Drive file",
        "google-form": "Google Form",
        "google-sheet": "Google Sheet",
        "google-slides": "Google Slides",
    }
    if kind in kind_labels:
        return kind_labels[kind]
    parsed = urlparse(url)
    filename = unquote(Path(parsed.path).name)
    if filename and filename not in {"edit", "view", "preview"}:
        return filename
    return parsed.netloc


def _update_owner_metadata(
    document: dict[str, object],
    *,
    title: str | None,
    context: str | None,
) -> bool:
    changed = False
    if title is not None and document.get("title") != title:
        document["title"] = title
        document["label"] = title
        changed = True
    if context is not None and document.get("context") != context:
        document["context"] = context
        changed = True
    return changed


def _reviewed_documents_by_id(
    review: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    if review is None:
        return {}
    return {
        cast(str, document["document_id"]): document
        for value in cast(list[object], review["documents"])
        if isinstance(value, dict)
        for document in [cast(dict[str, object], value)]
    }


def _normalize_optional_text(
    value: str | None,
    *,
    field: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        raise click.ClickException(f"{field} must not be empty.")
    if len(normalized) > max_length:
        raise click.ClickException(
            f"{field} must contain at most {max_length} characters."
        )
    return normalized


def _unescape_markdown_label(value: str) -> str:
    return re.sub(r"\\([\\`*{}\[\]()#+\-.!_>])", r"\1", value)


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"https", "http"} and bool(parsed.netloc)


def _truncate_inline(value: str, max_length: int) -> str:
    normalized = _safe_inline(value)
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def _safe_inline(value: str) -> str:
    return " ".join(value.replace("<!--", "&lt;!--").replace("-->", "--&gt;").split())


def _safe_code(value: str) -> str:
    return _safe_inline(value).replace("`", "'")


def _analysis_basis_hash(manifest: dict[str, object]) -> str:
    basis = {
        key: manifest[key]
        for key in (
            "review_id",
            "slug",
            "name",
            "classification",
            "review_on",
            "documents",
        )
    }
    encoded = json.dumps(
        basis,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _load_json(path: Path) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(
            f"Cannot read document-review record: {path}"
        ) from error
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid document-review record: {path}")
    return cast(dict[str, object], value)


def _write_json(path: Path, value: dict[str, object]) -> None:
    _replace_atomically(path, _json_bytes(value))


def _json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()


def _write_new_atomically(path: Path, content: bytes) -> None:
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
        os.link(temporary_path, path)
    except FileExistsError as error:
        raise click.ClickException(f"Document review already exists: {path}") from error
    finally:
        temporary_path.unlink(missing_ok=True)


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
        temporary_path.chmod(path.stat().st_mode if path.exists() else 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _remove_unchanged_file(path: Path, expected: bytes) -> None:
    try:
        if path.read_bytes() == expected:
            path.unlink()
    except OSError:
        pass
