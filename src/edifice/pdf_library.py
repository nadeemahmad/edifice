import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

import click

from edifice.identifiers import new_uuid7

DOCUMENT_KINDS = (
    "book",
    "book-chapter",
    "article",
    "research-paper",
    "judicial-opinion",
    "legal-filing",
    "statute-or-regulation",
    "report",
    "standard-or-specification",
    "official-document",
    "presentation",
    "memo",
    "manual",
    "thesis",
    "authored",
    "other",
)

FOLDER_BY_KIND = {
    "book": "books",
    "book-chapter": "books",
    "article": "papers-and-articles",
    "research-paper": "papers-and-articles",
    "judicial-opinion": "legal",
    "legal-filing": "legal",
    "statute-or-regulation": "legal",
    "report": "reports-and-official-documents",
    "standard-or-specification": "reports-and-official-documents",
    "official-document": "reports-and-official-documents",
    "presentation": "presentations",
    "memo": "reports-and-official-documents",
    "manual": "reports-and-official-documents",
    "thesis": "papers-and-articles",
    "authored": "authored",
    "other": "inbox",
}

PERSONAL_CLASSIFICATIONS = {"personal", "public"}
WORK_CLASSIFICATIONS = {
    "public",
    "netflix-internal",
    "netflix-confidential",
}

PDFKIT_METADATA_SCRIPT = r"""
ObjC.import("PDFKit");
ObjC.import("Foundation");

function stringValue(object) {
    if (!object) {
        return "";
    }
    const value = object.js;
    return typeof value === "undefined" ? "" : String(value);
}

function dateValue(object) {
    if (!object) {
        return "";
    }
    const value = stringValue(object);
    if (value) {
        return value;
    }
    return stringValue(object.description);
}

function run(argv) {
    const url = $.NSURL.fileURLWithPath(argv[0]);
    const document = $.PDFDocument.alloc.initWithURL(url);
    if (!document) {
        throw new Error("PDFKit could not open the document");
    }
    const attributes = document.documentAttributes;
    const page = Number(document.pageCount) > 0 ? document.pageAtIndex(0) : null;
    return JSON.stringify({
        title: attributes ? stringValue(attributes.objectForKey("Title")) : "",
        author: attributes ? stringValue(attributes.objectForKey("Author")) : "",
        creation_date: attributes
            ? dateValue(attributes.objectForKey("CreationDate"))
            : "",
        first_page_text: page ? stringValue(page.string).substring(0, 8000) : "",
        page_count: Number(document.pageCount)
    });
}
"""


@dataclass(frozen=True)
class PdfMetadata:
    title: str
    author: str
    creation_date: str
    first_page_text: str
    page_count: int
    evidence_status: str


@dataclass(frozen=True)
class PdfNaming:
    title: str
    creator: str
    year: int | None
    version: str
    document_kind: str
    folder: str
    canonical_filename: str
    confidence: str
    evidence_status: str


@dataclass(frozen=True)
class PdfAddResult:
    storage_path: Path
    catalog_path: Path
    canonical_filename: str
    sha256: str
    size_bytes: int
    duplicate: bool
    dry_run: bool


@dataclass(frozen=True)
class PdfInventory:
    verified: int
    unavailable: int
    mismatched: int
    uncataloged: int
    issues: tuple[str, ...]


@dataclass(frozen=True)
class PersonalBackupResult:
    copied: int
    verified: int
    drive_library_root: Path


@dataclass(frozen=True)
class _TitleCandidate:
    title: str
    start: int
    end: int
    score: int


def extract_pdf_metadata(pdf_path: Path) -> PdfMetadata:
    """Extract bounded metadata and first-page text with macOS PDFKit."""
    try:
        result = subprocess.run(
            [
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                PDFKIT_METADATA_SCRIPT,
                "--",
                str(pdf_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _unavailable_metadata()
    if result.returncode != 0:
        return _unavailable_metadata()
    try:
        payload: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _unavailable_metadata()
    if not isinstance(payload, dict):
        return _unavailable_metadata()
    typed = cast(dict[str, object], payload)
    title = typed.get("title")
    author = typed.get("author")
    creation_date = typed.get("creation_date")
    first_page_text = typed.get("first_page_text")
    page_count = typed.get("page_count")
    if not all(
        isinstance(value, str)
        for value in (title, author, creation_date, first_page_text)
    ) or not isinstance(page_count, int):
        return _unavailable_metadata()
    return PdfMetadata(
        title=cast(str, title).strip(),
        author=cast(str, author).strip(),
        creation_date=cast(str, creation_date).strip(),
        first_page_text=cast(str, first_page_text).strip(),
        page_count=max(page_count, 0),
        evidence_status="verified",
    )


def add_pdf(
    *,
    vault_root: Path,
    audit_root: Path,
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
    dry_run: bool,
    source_system: str = "local",
    original_filename: str | None = None,
) -> PdfAddResult:
    """Copy one selected PDF into the governed local library."""
    normalized_source = _validate_pdf_path(source_pdf)
    normalized_scope = _validate_scope(scope)
    normalized_classification = _validate_classification(
        normalized_scope,
        classification,
    )
    normalized_source_url = _validate_source_url(normalized_scope, source_url)
    normalized_kind = _validate_document_kind(document_kind)

    content = normalized_source.read_bytes()
    metadata, naming = propose_pdf_naming(
        content=content,
        original_filename=original_filename or normalized_source.name,
        document_kind=normalized_kind,
        title_override=title,
        creator_override=creator,
        year_override=year,
        version_override=version,
    )
    content_hash = _sha256(content)
    if naming.confidence != "high" and not accept_name and not dry_run:
        raise click.ClickException(
            f"Proposed PDF name has {naming.confidence} confidence: "
            f"{naming.canonical_filename}. Rerun with --accept-name or provide "
            "--title and related overrides."
        )

    settings = _scope_settings(vault_root, normalized_scope)
    proposed_storage_path = (
        settings.pdf_root / naming.folder / naming.canonical_filename
    )
    relative_storage_path = proposed_storage_path.relative_to(vault_root)
    if dry_run:
        return PdfAddResult(
            storage_path=relative_storage_path,
            catalog_path=settings.catalog_markdown.relative_to(vault_root),
            canonical_filename=naming.canonical_filename,
            sha256=content_hash,
            size_bytes=len(content),
            duplicate=False,
            dry_run=True,
        )

    with _pdf_lock(audit_root, normalized_scope):
        index = _load_index(settings.catalog_index, normalized_scope)
        existing = _find_by_hash(index, content_hash)
        if existing is not None:
            existing_path = vault_root / cast(str, existing["storage_path"])
            if (
                not existing_path.is_file()
                or _sha256(existing_path.read_bytes()) != content_hash
            ):
                raise click.ClickException(
                    f"Refusing to overwrite a different PDF: {existing_path}"
                )
            return PdfAddResult(
                storage_path=Path(cast(str, existing["storage_path"])),
                catalog_path=settings.catalog_markdown.relative_to(vault_root),
                canonical_filename=cast(str, existing["canonical_filename"]),
                sha256=content_hash,
                size_bytes=cast(int, existing["size_bytes"]),
                duplicate=True,
                dry_run=False,
            )

        storage_path = _resolve_storage_collision(
            proposed_storage_path,
            content_hash,
        )
        relative_storage_path = storage_path.relative_to(vault_root)
        artifact: dict[str, object] = {
            "id": f"pdf-artifact-{new_uuid7()}",
            "scope": normalized_scope,
            "title": naming.title,
            "creator": naming.creator,
            "year": naming.year,
            "version": naming.version,
            "document_kind": naming.document_kind,
            "classification": normalized_classification,
            "source_url": normalized_source_url,
            "source_system": _clean_display_value(source_system) or "local",
            "original_filename": _validate_original_filename(
                original_filename or normalized_source.name
            ),
            "canonical_filename": storage_path.name,
            "storage_path": relative_storage_path.as_posix(),
            "sha256": content_hash,
            "size_bytes": len(content),
            "page_count": metadata.page_count,
            "metadata_evidence": metadata.evidence_status,
            "naming_evidence": naming.evidence_status,
            "naming_confidence": naming.confidence,
            "added_at": datetime.now(UTC).isoformat(),
        }
        artifacts = cast(list[object], index["artifacts"])
        artifacts.append(artifact)
        artifacts.sort(
            key=lambda item: cast(
                str,
                cast(dict[str, object], item)["canonical_filename"],
            )
        )

        previous_index = _read_optional(settings.catalog_index)
        previous_catalog = _read_optional(settings.catalog_markdown)
        created_pdf = False
        try:
            if not storage_path.exists():
                _write_new_file(storage_path, content)
                created_pdf = True
            _replace_atomically(
                settings.catalog_index,
                (
                    json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n"
                ).encode(),
            )
            _replace_atomically(
                settings.catalog_markdown,
                _render_catalog(
                    index=index,
                    vault_root=vault_root,
                    catalog_path=settings.catalog_markdown,
                ).encode(),
            )
            _append_pdf_audit_event(
                audit_root=audit_root,
                artifact=artifact,
            )
        except Exception:
            try:
                _restore_file(settings.catalog_index, previous_index)
                _restore_file(settings.catalog_markdown, previous_catalog)
            finally:
                if created_pdf:
                    storage_path.unlink(missing_ok=True)
            raise

    return PdfAddResult(
        storage_path=relative_storage_path,
        catalog_path=settings.catalog_markdown.relative_to(vault_root),
        canonical_filename=storage_path.name,
        sha256=content_hash,
        size_bytes=len(content),
        duplicate=False,
        dry_run=False,
    )


def propose_pdf_naming(
    *,
    content: bytes,
    original_filename: str,
    document_kind: str | None,
    title_override: str | None,
    creator_override: str | None,
    year_override: int | None,
    version_override: str | None,
) -> tuple[PdfMetadata, PdfNaming]:
    """Extract metadata and derive a canonical name from one byte snapshot."""
    if not content.startswith(b"%PDF-"):
        raise click.ClickException("Content does not have a PDF header.")
    validated_filename = _validate_original_filename(original_filename)
    with tempfile.TemporaryDirectory(prefix="edifice-pdf-") as temporary_root:
        snapshot_path = Path(temporary_root) / "snapshot.pdf"
        snapshot_path.write_bytes(content)
        metadata = extract_pdf_metadata(snapshot_path)
    naming = _derive_naming(
        source_pdf=Path(validated_filename),
        metadata=metadata,
        document_kind=document_kind,
        title_override=title_override,
        creator_override=creator_override,
        year_override=year_override,
        version_override=version_override,
    )
    return metadata, naming


def inventory_pdfs(vault_root: Path) -> PdfInventory:
    """Verify catalog entries and report uncataloged local PDF copies."""
    verified = 0
    unavailable = 0
    mismatched = 0
    cataloged_paths: set[Path] = set()
    issues: list[str] = []

    for scope in ("personal", "work"):
        settings = _scope_settings(vault_root, scope)
        index = _load_index(settings.catalog_index, scope)
        for item in cast(list[object], index["artifacts"]):
            artifact = cast(dict[str, object], item)
            storage_path = vault_root / cast(str, artifact["storage_path"])
            cataloged_paths.add(storage_path.resolve())
            if not storage_path.is_file():
                unavailable += 1
                issues.append(
                    f"[unavailable] {storage_path.relative_to(vault_root).as_posix()}"
                )
                continue
            if _sha256(storage_path.read_bytes()) != artifact["sha256"]:
                mismatched += 1
                issues.append(
                    f"[mismatched] {storage_path.relative_to(vault_root).as_posix()}"
                )
                continue
            verified += 1

    local_pdfs = {
        path.resolve()
        for scope in ("personal", "work")
        for path in _scope_settings(vault_root, scope).pdf_root.rglob("*.pdf")
        if path.is_file()
    }
    uncataloged_paths = sorted(local_pdfs - cataloged_paths)
    issues.extend(
        f"[uncataloged] {path.relative_to(vault_root).as_posix()}"
        for path in uncataloged_paths
    )
    return PdfInventory(
        verified=verified,
        unavailable=unavailable,
        mismatched=mismatched,
        uncataloged=len(uncataloged_paths),
        issues=tuple(issues),
    )


def backup_personal_pdfs(
    *,
    vault_root: Path,
    audit_root: Path,
    drive_library_root: Path,
) -> PersonalBackupResult:
    """Copy every cataloged personal PDF into a Drive-backed library."""
    if not drive_library_root.is_absolute():
        raise click.ClickException("Personal Drive library path must be absolute.")
    normalized_drive_root = drive_library_root.expanduser().resolve()
    settings = _scope_settings(vault_root, "personal")
    local_pdf_root = settings.pdf_root.resolve()
    copied = 0
    verified = 0

    with _pdf_lock(audit_root, "personal"):
        index = _load_index(settings.catalog_index, "personal")
        artifacts = cast(list[object], index["artifacts"])
        for item in artifacts:
            artifact = cast(dict[str, object], item)
            source_path = (vault_root / cast(str, artifact["storage_path"])).resolve()
            if not source_path.is_relative_to(local_pdf_root):
                raise click.ClickException(
                    f"Personal PDF is outside the managed library: {source_path}"
                )
            if not source_path.is_file():
                raise click.ClickException(
                    f"Personal PDF is unavailable: {source_path}"
                )
            relative_path = source_path.relative_to(local_pdf_root)
            destination_path = normalized_drive_root / relative_path
            expected_hash = cast(str, artifact["sha256"])
            source_content = source_path.read_bytes()
            if _sha256(source_content) != expected_hash:
                raise click.ClickException(f"Personal PDF hash mismatch: {source_path}")
            if destination_path.exists():
                if (
                    not destination_path.is_file()
                    or _sha256(destination_path.read_bytes()) != expected_hash
                ):
                    raise click.ClickException(
                        "Refusing to overwrite different Drive bytes: "
                        f"{destination_path}"
                    )
            else:
                _write_exclusive_file(destination_path, source_content)
                copied += 1
            if _sha256(destination_path.read_bytes()) != expected_hash:
                raise click.ClickException(
                    f"Drive copy hash mismatch: {destination_path}"
                )
            verified += 1
            artifact["drive_path"] = (
                Path(normalized_drive_root.name) / relative_path
            ).as_posix()
            artifact["drive_copy_status"] = "local-hash-verified"
            artifact["drive_sync_status"] = "unavailable"
            artifact["drive_verified_at"] = datetime.now(UTC).isoformat()

        _replace_atomically(
            settings.catalog_index,
            (
                json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            ).encode(),
        )
        _replace_atomically(
            settings.catalog_markdown,
            _render_catalog(
                index=index,
                vault_root=vault_root,
                catalog_path=settings.catalog_markdown,
            ).encode(),
        )
        _append_pdf_backup_audit_event(
            audit_root=audit_root,
            copied=copied,
            verified=verified,
            drive_library_root=normalized_drive_root,
        )

    return PersonalBackupResult(
        copied=copied,
        verified=verified,
        drive_library_root=normalized_drive_root,
    )


@dataclass(frozen=True)
class _ScopeSettings:
    scope: str
    pdf_root: Path
    catalog_index: Path
    catalog_markdown: Path


def _scope_settings(vault_root: Path, scope: str) -> _ScopeSettings:
    if scope == "personal":
        catalog_root = vault_root / "10-personal" / "operations" / "artifacts"
        return _ScopeSettings(
            scope=scope,
            pdf_root=vault_root / "10-personal" / "artifacts" / "pdfs",
            catalog_index=catalog_root / "pdf-catalog.json",
            catalog_markdown=catalog_root / "pdf-catalog.md",
        )
    return _ScopeSettings(
        scope=scope,
        pdf_root=vault_root / "20-work" / "references" / "pdfs",
        catalog_index=vault_root / "20-work" / "references" / "pdf-catalog.json",
        catalog_markdown=vault_root / "20-work" / "references" / "pdf-catalog.md",
    )


def _validate_scope(scope: str) -> str:
    normalized = scope.strip().lower()
    if normalized not in {"personal", "work"}:
        raise click.ClickException(f"Invalid PDF scope: {scope}")
    return normalized


def _validate_classification(scope: str, classification: str) -> str:
    normalized = classification.strip().lower()
    allowed = PERSONAL_CLASSIFICATIONS if scope == "personal" else WORK_CLASSIFICATIONS
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise click.ClickException(
            f"Invalid {scope} PDF classification: {classification}. "
            f"Choose one of: {choices}."
        )
    return normalized


def _validate_source_url(scope: str, source_url: str | None) -> str | None:
    if source_url is None:
        if scope == "work":
            raise click.ClickException("Work PDFs require an authoritative source URL.")
        return None
    normalized = source_url.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() for character in normalized)
    ):
        raise click.ClickException(f"Invalid PDF source URL: {source_url}")
    return normalized


def _validate_document_kind(document_kind: str | None) -> str | None:
    if document_kind is None:
        return None
    normalized = document_kind.strip().lower()
    if normalized not in DOCUMENT_KINDS:
        raise click.ClickException(f"Invalid PDF document kind: {document_kind}")
    return normalized


def _validate_original_filename(value: str) -> str:
    filename = Path(value).name.strip()
    if not filename or filename in {".", ".."}:
        raise click.ClickException("Original PDF filename must not be empty.")
    return filename


def _validate_pdf_path(source_pdf: Path) -> Path:
    if not source_pdf.is_absolute():
        raise click.ClickException("PDF path must be absolute.")
    resolved = source_pdf.expanduser().resolve()
    if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
        raise click.ClickException(f"Not a readable PDF file: {source_pdf}")
    with resolved.open("rb") as source:
        if source.read(5) != b"%PDF-":
            raise click.ClickException(f"File does not have a PDF header: {source_pdf}")
    return resolved


def _derive_naming(
    *,
    source_pdf: Path,
    metadata: PdfMetadata,
    document_kind: str | None,
    title_override: str | None,
    creator_override: str | None,
    year_override: int | None,
    version_override: str | None,
) -> PdfNaming:
    title_candidate = _first_page_title_candidate(metadata.first_page_text)
    title, confidence, naming_evidence = _select_title(
        source_pdf,
        metadata,
        title_override,
        title_candidate,
    )
    metadata_creator = _clean_display_value(metadata.author)
    if _is_generic_metadata(metadata_creator):
        metadata_creator = ""
    creator = _clean_display_value(creator_override or metadata_creator)
    if not creator and title_candidate is not None:
        creator = _infer_creator(metadata.first_page_text, title_candidate)
    year = (
        year_override
        or _extract_printed_year(metadata.first_page_text)
        or _extract_year(metadata.creation_date)
    )
    version = _clean_display_value(
        version_override or _extract_version(metadata.first_page_text)
    )
    kind = document_kind or _infer_document_kind(metadata.first_page_text)
    folder = FOLDER_BY_KIND[kind]
    components = _filename_components(
        document_kind=kind,
        title=title,
        creator=creator,
        year=year,
        version=version,
    )
    canonical_filename = f"{_kebab_join(components)}.pdf"
    return PdfNaming(
        title=title,
        creator=creator,
        year=year,
        version=version,
        document_kind=kind,
        folder=folder,
        canonical_filename=canonical_filename,
        confidence=confidence,
        evidence_status=naming_evidence,
    )


def _select_title(
    source_pdf: Path,
    metadata: PdfMetadata,
    title_override: str | None,
    title_candidate: _TitleCandidate | None,
) -> tuple[str, str, str]:
    if title_override and title_override.strip():
        return _clean_display_value(title_override), "high", "owner-attested"
    metadata_title = _clean_display_value(metadata.title)
    if metadata_title and not _is_generic_metadata(metadata_title):
        return metadata_title, "high", metadata.evidence_status
    if title_candidate is not None:
        return title_candidate.title, "medium", metadata.evidence_status
    fallback_title = _clean_display_value(source_pdf.stem)
    metadata_author = _clean_display_value(metadata.author)
    if not _is_generic_metadata(metadata_author) and _looks_human_filename(
        fallback_title
    ):
        return fallback_title, "medium", metadata.evidence_status
    return fallback_title, "low", "unavailable"


def _first_page_title_candidate(first_page_text: str) -> _TitleCandidate | None:
    lines = [_clean_display_value(line) for line in first_page_text.splitlines()[:25]]
    candidates: list[_TitleCandidate] = []
    for start, line in enumerate(lines):
        if not line or _is_title_boilerplate(line) or _looks_like_institution(line):
            continue
        title = line
        end = start
        for next_index in range(start + 1, min(start + 3, len(lines))):
            next_line = lines[next_index]
            if not _should_join_title_line(title, next_line):
                break
            title = _join_title_lines(title, next_line)
            end = next_index
        score = _title_score(title, start)
        if score > 0:
            candidates.append(
                _TitleCandidate(
                    title=title,
                    start=start,
                    end=end,
                    score=score,
                )
            )
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.score, -candidate.start))


def _is_title_boilerplate(line: str) -> bool:
    lower = line.casefold()
    return (
        lower.startswith(
            (
                "http://",
                "https://",
                "arxiv:",
                "doi:",
                "provided proper attribution",
                "reproduce the tables",
                "scholarly works",
                "this content downloaded",
                "all use subject",
                "copyright ",
                "© ",
                "bmj ",
                "research methods & reporting",
            )
        )
        or "@" in line
        or lower in {"abstract", "contents", "table of contents"}
        or (
            "," in line
            and any(
                role in lower
                for role in (" director", " professor", " honorary", " fellow")
            )
        )
        or re.match(r"^\d{1,3}(?:\.\d{1,3}){3}\b", line) is not None
    )


def _should_join_title_line(current: str, next_line: str) -> bool:
    if (
        not next_line
        or _is_title_boilerplate(next_line)
        or _looks_like_author(next_line)
        or _looks_like_institution(next_line)
    ):
        return False
    current_words = current.split()
    next_words = next_line.split()
    last_word = current_words[-1].casefold().rstrip("-:") if current_words else ""
    return (
        current.endswith("-")
        or last_word in {"a", "an", "and", "for", "in", "of", "the", "to", "with"}
        or next_line[:1].islower()
        or (
            len(current_words) == 1
            and len(next_words) <= 4
            and current.isupper()
            and next_line.isupper()
        )
    )


def _join_title_lines(current: str, next_line: str) -> str:
    if current.endswith("-"):
        return f"{current[:-1]}{next_line}"
    return f"{current} {next_line}"


def _title_score(title: str, start: int) -> int:
    words = title.split()
    if not words or len(words) > 20 or len(title) > 200:
        return -100
    if _is_generic_metadata(title) or _is_title_boilerplate(title):
        return -100
    letters = [character for character in title if character.isalpha()]
    if len(letters) < 4:
        return -100
    score = min(len(words), 12)
    if 2 <= len(words) <= 15:
        score += 20
    elif len(words) == 1:
        score += 4
    title_words = [
        word for word in words if any(character.isalpha() for character in word)
    ]
    title_like = sum(word.isupper() or word[:1].isupper() for word in title_words)
    if title_words and title_like / len(title_words) >= 0.6:
        score += 8
    score += max(0, 8 - start)
    if title.endswith((".", ";")):
        score -= 8
    return score


def _infer_creator(
    first_page_text: str,
    title_candidate: _TitleCandidate,
) -> str:
    lines = [_clean_display_value(line) for line in first_page_text.splitlines()[:30]]
    creators: list[str] = []
    for line in lines[title_candidate.end + 1 : title_candidate.end + 9]:
        if _looks_like_author(line):
            creators.append(_clean_author(line))
            if len(creators) == 2:
                break
        elif creators:
            break
    if not creators:
        return ""
    return f"{creators[0]} et al" if len(creators) > 1 else creators[0]


def _looks_like_author(line: str) -> bool:
    cleaned = _clean_author(line)
    words = cleaned.split()
    if not 2 <= len(words) <= 7 or any(character.isdigit() for character in cleaned):
        return False
    if _looks_like_institution(cleaned):
        return False
    connectors = {"and", "de", "del", "van", "von"}
    return all(
        word.casefold() in connectors or word.isupper() or word[:1].isupper()
        for word in words
    )


def _looks_like_institution(line: str) -> bool:
    lower = f" {line.casefold()} "
    return any(
        marker in lower
        for marker in (
            " university ",
            " institute ",
            " department ",
            " school ",
            " google ",
            " research ",
            " press ",
            " edition ",
            " version ",
            " leadership ",
            " spring ",
            " abstract ",
        )
    )


def _clean_author(line: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ.' -]+", "", line)
    normalized = _clean_display_value(cleaned)
    return normalized.title() if normalized.isupper() else normalized


def _is_generic_metadata(value: str) -> bool:
    normalized = _clean_display_value(value).casefold()
    return normalized in {
        "",
        "document",
        "front matter",
        "scan",
        "unknown",
        "untitled",
    } or normalized.startswith("resource-")


def _looks_human_filename(value: str) -> bool:
    words = re.findall(r"[^\W\d_]+", value, flags=re.UNICODE)
    return len(words) >= 3 and not re.fullmatch(r"[A-Za-z0-9_-]{32,}", value)


def _infer_document_kind(first_page_text: str) -> str:
    text = f" {first_page_text.casefold()} "
    if " isbn " in text:
        return "book"
    if (
        " abstract " in text
        or " arxiv:" in text
        or " doi:" in text
        or " doi.org/" in text
    ):
        return "research-paper"
    if " supreme court " in text or " court of appeals " in text:
        return "judicial-opinion"
    if " statute " in text or " regulation " in text:
        return "statute-or-regulation"
    if " standard " in text or " specification " in text:
        return "standard-or-specification"
    if " memorandum " in text or " memo " in text:
        return "memo"
    if " thesis " in text or " dissertation " in text:
        return "thesis"
    if " annual report " in text or " technical report " in text:
        return "report"
    return "other"


def _extract_printed_year(first_page_text: str) -> int | None:
    for line in first_page_text.splitlines()[:8]:
        match = re.search(r"(19|20)\d{2}", line)
        if match:
            return int(match.group())
    return None


def _extract_version(first_page_text: str) -> str:
    first_lines = "\n".join(first_page_text.splitlines()[:20])
    match = re.search(
        r"\b\d+(?:st|nd|rd|th)\s+edition(?:\s+version\s+[0-9.]+)?\b",
        first_lines,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_display_value(match.group())
    match = re.search(
        r"\bversion\s+[0-9]+(?:\.[0-9]+)*\b",
        first_lines,
        flags=re.IGNORECASE,
    )
    return _clean_display_value(match.group()) if match else ""


def _filename_components(
    *,
    document_kind: str,
    title: str,
    creator: str,
    year: int | None,
    version: str,
) -> list[str]:
    if document_kind == "authored":
        values: list[str | int | None] = [title, version, year]
    else:
        values = [creator, title, version, year]
    return [str(value) for value in values if value not in {None, ""}]


def _kebab_join(components: list[str]) -> str:
    joined = "-".join(_kebab(component) for component in components)
    compact = re.sub(r"-+", "-", joined).strip("-")
    if not compact:
        compact = "document"
    if len(compact) > 160:
        compact = compact[:160].rstrip("-")
    return compact


def _kebab(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "-", normalized, flags=re.UNICODE).strip("-")


def _clean_display_value(value: str) -> str:
    without_controls = "".join(
        " " if unicodedata.category(character).startswith("C") else character
        for character in value
    )
    return " ".join(without_controls.split()).strip()


def _extract_year(value: str) -> int | None:
    match = re.search(r"(19|20)\d{2}", value)
    return int(match.group()) if match else None


def _load_index(path: Path, scope: str) -> dict[str, object]:
    if not path.exists():
        return {"schema_version": 1, "scope": scope, "artifacts": []}
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read PDF catalog: {path}") from error
    if not isinstance(parsed, dict):
        raise click.ClickException(f"Invalid PDF catalog: {path}")
    typed = cast(dict[str, object], parsed)
    if (
        typed.get("schema_version") != 1
        or typed.get("scope") != scope
        or not isinstance(typed.get("artifacts"), list)
    ):
        raise click.ClickException(f"Invalid PDF catalog: {path}")
    return typed


def _find_by_hash(
    index: dict[str, object],
    content_hash: str,
) -> dict[str, object] | None:
    for item in cast(list[object], index["artifacts"]):
        if not isinstance(item, dict):
            raise click.ClickException("Invalid PDF catalog artifact.")
        typed = cast(dict[str, object], item)
        if typed.get("sha256") == content_hash:
            return typed
    return None


def _resolve_storage_collision(path: Path, content_hash: str) -> Path:
    if not path.exists() or _sha256(path.read_bytes()) == content_hash:
        return path
    candidate = path.with_stem(f"{path.stem}-{content_hash.split(':', 1)[1][:8]}")
    if not candidate.exists() or _sha256(candidate.read_bytes()) == content_hash:
        return candidate
    return path.with_stem(f"{path.stem}-{content_hash.split(':', 1)[1]}")


def _render_catalog(
    *,
    index: dict[str, object],
    vault_root: Path,
    catalog_path: Path,
) -> str:
    scope = cast(str, index["scope"])
    lines = [
        "---",
        "type: pdf-catalog",
        "schema_version: 1",
        f"scope: {scope}",
        "---",
        "",
        f"# {scope.title()} PDF catalog",
        "",
        "| Title | Kind | File | Classification | Drive | SHA-256 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in cast(list[object], index["artifacts"]):
        artifact = cast(dict[str, object], item)
        storage_path = vault_root / cast(str, artifact["storage_path"])
        relative_link = os.path.relpath(storage_path, catalog_path.parent)
        title = _catalog_text(cast(str, artifact["title"]))
        drive_status = cast(str, artifact.get("drive_copy_status", "not-configured"))
        lines.append(
            f"| {title} | `{artifact['document_kind']}` | "
            f"[{artifact['canonical_filename']}](<{Path(relative_link).as_posix()}>) | "
            f"`{artifact['classification']}` | `{drive_status}` | "
            f"`{artifact['sha256']}` |"
        )
    if len(lines) == 10:
        lines.append("| No PDFs cataloged. |  |  |  |  |  |")
    return "\n".join(lines) + "\n"


def _catalog_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _write_new_file(path: Path, content: bytes) -> None:
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
    except FileExistsError:
        if _sha256(path.read_bytes()) != _sha256(content):
            raise click.ClickException(f"Refusing to overwrite PDF: {path}") from None
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_exclusive_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        if _sha256(path.read_bytes()) != _sha256(content):
            raise click.ClickException(
                f"Refusing to overwrite different Drive bytes: {path}"
            ) from None
        return
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("Drive copy write made no progress.")
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    else:
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
        temporary_path.chmod(path.stat().st_mode if path.exists() else 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_optional(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _restore_file(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    _replace_atomically(path, content)


def _append_pdf_audit_event(
    *,
    audit_root: Path,
    artifact: dict[str, object],
) -> None:
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_path = audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": artifact["scope"],
        "event_type": "pdf.added",
        "artifact_id": artifact["id"],
        "target": f"vault://edifice/{artifact['storage_path']}",
        "sha256": artifact["sha256"],
        "classification": artifact["classification"],
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


def _append_pdf_backup_audit_event(
    *,
    audit_root: Path,
    copied: int,
    verified: int,
    drive_library_root: Path,
) -> None:
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_path = audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "personal",
        "event_type": "pdf.drive-backed",
        "target": f"file://{drive_library_root}",
        "copied": copied,
        "verified": verified,
        "drive_copy_status": "local-hash-verified",
        "drive_sync_status": "unavailable",
        "external_mutation": True,
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


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _unavailable_metadata() -> PdfMetadata:
    return PdfMetadata(
        title="",
        author="",
        creation_date="",
        first_page_text="",
        page_count=0,
        evidence_status="unavailable",
    )


@contextmanager
def _pdf_lock(audit_root: Path, scope: str) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / f"pdf-{scope}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
