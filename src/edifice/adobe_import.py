import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import click

from edifice.identifiers import new_uuid7
from edifice.pdf_library import add_pdf, propose_pdf_naming

MAX_ADOBE_CANDIDATES = 2000


@dataclass(frozen=True)
class AdobePlanResult:
    manifest_path: Path
    review_path: Path
    candidate_count: int
    duplicate_source_files: int
    source_completeness: str


@dataclass(frozen=True)
class AdobeApplyResult:
    imported: int
    already_imported: int
    skipped: int
    manifest_path: Path


def default_adobe_cache_roots() -> tuple[Path, ...]:
    """Return configured or standard Acrobat local cloud-cache roots."""
    configured = os.environ.get("EDIFICE_ADOBE_CACHE_ROOTS")
    if configured is not None:
        return tuple(
            Path(value).expanduser().resolve()
            for value in configured.split(os.pathsep)
            if value
        )
    acrobat_root = (
        Path.home() / "Library" / "Application Support" / "Adobe" / "Acrobat" / "DC"
    )
    return (
        acrobat_root / "BHCache" / "Acrobat" / "Files",
        acrobat_root / "Acrobat" / "Synchronizer" / "SyncUploadDir",
        acrobat_root / "EurekaReviewDocuments_V2",
    )


def plan_adobe_import(
    *,
    vault_root: Path,
    cache_roots: tuple[Path, ...],
    export_dir: Path | None,
    export_complete: bool,
) -> AdobePlanResult:
    """Create a non-importing review manifest from available Adobe PDF bytes."""
    if export_complete and export_dir is None:
        raise click.ClickException("--export-complete requires --export-dir.")
    normalized_export = _normalize_export_dir(export_dir)
    roots: list[dict[str, object]] = [
        *(
            {"kind": "acrobat-cache", "path": root}
            for root in cache_roots
            if root.is_dir()
        ),
    ]
    if normalized_export is not None:
        roots.append({"kind": "adobe-export", "path": normalized_export})
    if not roots:
        raise click.ClickException("No Adobe cache or export directory is available.")

    discovered = _discover_pdf_files(roots)
    if not discovered:
        raise click.ClickException("No PDF files were found in the Adobe sources.")
    if len(discovered) > MAX_ADOBE_CANDIDATES:
        raise click.ClickException(
            f"Adobe import found more than {MAX_ADOBE_CANDIDATES} PDF files."
        )

    grouped: dict[str, list[dict[str, object]]] = {}
    for source in discovered:
        source_path = cast(Path, source["path"])
        content_hash = _sha256(source_path.read_bytes())
        grouped.setdefault(content_hash, []).append(source)

    candidates: list[dict[str, object]] = []
    duplicate_source_files = 0
    for content_hash, sources in sorted(grouped.items()):
        selected = min(
            sources,
            key=lambda source: _source_preference(cast(Path, source["path"])),
        )
        selected_path = cast(Path, selected["path"])
        content = selected_path.read_bytes()
        original_filename = _display_filename(selected_path)
        metadata, naming = propose_pdf_naming(
            content=content,
            original_filename=original_filename,
            document_kind=None,
            title_override=None,
            creator_override=None,
            year_override=None,
            version_override=None,
        )
        source_paths = sorted(str(cast(Path, source["path"])) for source in sources)
        duplicate_source_files += len(sources) - 1
        candidates.append(
            {
                "id": f"adobe-pdf-{new_uuid7()}",
                "decision": "review",
                "status": "planned",
                "source_kind": cast(str, selected["kind"]),
                "source_paths": source_paths,
                "selected_source_path": str(selected_path),
                "original_filename": original_filename,
                "sha256": content_hash,
                "size_bytes": len(content),
                "page_count": metadata.page_count,
                "metadata_evidence": metadata.evidence_status,
                "title": naming.title,
                "creator": naming.creator,
                "year": naming.year,
                "version": naming.version,
                "document_kind": naming.document_kind,
                "proposed_filename": naming.canonical_filename,
                "naming_confidence": naming.confidence,
            }
        )

    candidates.sort(key=lambda candidate: cast(str, candidate["proposed_filename"]))
    completeness = "owner-attested" if export_complete else "trial-required"
    now = datetime.now(UTC)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "manifest_id": f"adobe-import-{new_uuid7()}",
        "created_at": now.isoformat(),
        "source_system": "adobe-cloud",
        "source_completeness": completeness,
        "external_mutation": False,
        "source_roots": [
            {
                "kind": cast(str, root["kind"]),
                "path": str(cast(Path, root["path"])),
            }
            for root in roots
        ],
        "candidate_count": len(candidates),
        "duplicate_source_files": duplicate_source_files,
        "candidates": candidates,
    }
    imports_root = vault_root / "10-personal" / "operations" / "artifacts" / "imports"
    stem = f"adobe-cloud-{now.strftime('%Y-%m-%d-%H%M%S')}-{str(new_uuid7())[:8]}"
    manifest_path = imports_root / f"{stem}.json"
    review_path = imports_root / f"{stem}.md"
    _replace_atomically(manifest_path, _encode_manifest(manifest))
    _replace_atomically(review_path, _render_review(manifest).encode())
    return AdobePlanResult(
        manifest_path=manifest_path.relative_to(vault_root),
        review_path=review_path.relative_to(vault_root),
        candidate_count=len(candidates),
        duplicate_source_files=duplicate_source_files,
        source_completeness=completeness,
    )


def apply_adobe_import(
    *,
    vault_root: Path,
    audit_root: Path,
    manifest_path: Path,
    allow_incomplete_source: bool,
    confirm_all_personal: bool,
) -> AdobeApplyResult:
    """Import approved Adobe candidates without mutating their sources."""
    normalized_manifest = _validate_manifest_path(vault_root, manifest_path)
    manifest = _load_manifest(normalized_manifest)
    completeness = cast(str, manifest["source_completeness"])
    if completeness != "owner-attested" and not allow_incomplete_source:
        raise click.ClickException(
            "Adobe cache coverage is incomplete. Rerun with "
            "--allow-incomplete-source to import only materialized files."
        )

    candidates = cast(list[object], manifest["candidates"])
    if confirm_all_personal:
        for item in candidates:
            candidate = cast(dict[str, object], item)
            if candidate.get("decision") == "review":
                candidate["decision"] = "import-personal"
    pending = [
        cast(dict[str, object], item)
        for item in candidates
        if cast(dict[str, object], item).get("decision") == "review"
    ]
    if pending:
        raise click.ClickException(
            f"{len(pending)} Adobe PDFs still require review. Edit decisions "
            "or rerun with --confirm-all-personal."
        )

    source_roots = _manifest_source_roots(manifest)
    imported = 0
    already_imported = 0
    skipped = 0
    for item in candidates:
        candidate = cast(dict[str, object], item)
        decision = candidate.get("decision")
        if decision == "skip":
            skipped += 1
            continue
        if decision != "import-personal":
            raise click.ClickException(f"Invalid Adobe import decision: {decision}")
        if candidate.get("status") == "imported":
            already_imported += 1
            continue

        source_path = Path(cast(str, candidate["selected_source_path"])).resolve()
        if not any(source_path.is_relative_to(root) for root in source_roots):
            raise click.ClickException(
                f"Adobe source is outside the planned roots: {source_path}"
            )
        if not source_path.is_file():
            raise click.ClickException(f"Adobe source is unavailable: {source_path}")
        content = source_path.read_bytes()
        if _sha256(content) != candidate["sha256"]:
            raise click.ClickException(
                f"Adobe source changed after the Adobe import plan: {source_path}"
            )

        original_filename = cast(str, candidate["original_filename"])
        temporary_name = (
            original_filename
            if original_filename.lower().endswith(".pdf")
            else f"{original_filename}.pdf"
        )
        with tempfile.TemporaryDirectory(prefix="edifice-adobe-") as temporary_root:
            temporary_pdf = Path(temporary_root) / Path(temporary_name).name
            temporary_pdf.write_bytes(content)
            result = add_pdf(
                vault_root=vault_root,
                audit_root=audit_root,
                source_pdf=temporary_pdf,
                scope="personal",
                classification="personal",
                source_url=None,
                document_kind=cast(str, candidate["document_kind"]),
                title=cast(str, candidate["title"]),
                creator=cast(str, candidate["creator"]),
                year=_optional_int(candidate.get("year")),
                version=cast(str, candidate["version"]),
                accept_name=True,
                dry_run=False,
                source_system="adobe-cloud",
                original_filename=original_filename,
            )
        candidate["decision"] = "import-personal"
        candidate["status"] = "imported"
        candidate["storage_path"] = result.storage_path.as_posix()
        candidate["imported_at"] = datetime.now(UTC).isoformat()
        candidate["duplicate_in_library"] = result.duplicate
        imported += 1
        _replace_atomically(normalized_manifest, _encode_manifest(manifest))
        _replace_atomically(
            normalized_manifest.with_suffix(".md"),
            _render_review(manifest).encode(),
        )

    return AdobeApplyResult(
        imported=imported,
        already_imported=already_imported,
        skipped=skipped,
        manifest_path=normalized_manifest.relative_to(vault_root),
    )


def _normalize_export_dir(export_dir: Path | None) -> Path | None:
    if export_dir is None:
        return None
    if not export_dir.is_absolute():
        raise click.ClickException("Adobe export directory must be absolute.")
    resolved = export_dir.expanduser().resolve()
    if not resolved.is_dir():
        raise click.ClickException(
            f"Adobe export directory is unavailable: {export_dir}"
        )
    return resolved


def _discover_pdf_files(roots: list[dict[str, object]]) -> list[dict[str, object]]:
    discovered: list[dict[str, object]] = []
    for root in roots:
        root_path = cast(Path, root["path"])
        for path in root_path.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                with path.open("rb") as source:
                    is_pdf = source.read(5) == b"%PDF-"
            except OSError:
                continue
            if is_pdf:
                discovered.append(
                    {
                        "kind": root["kind"],
                        "path": path.resolve(),
                    }
                )
    return discovered


def _source_preference(path: Path) -> tuple[bool, int, str]:
    return (path.suffix.lower() != ".pdf", len(path.name), path.name.casefold())


def _display_filename(path: Path) -> str:
    return path.name if path.suffix.lower() == ".pdf" else f"{path.name}.pdf"


def _validate_manifest_path(vault_root: Path, manifest_path: Path) -> Path:
    resolved = manifest_path.expanduser().resolve()
    imports_root = (
        vault_root / "10-personal" / "operations" / "artifacts" / "imports"
    ).resolve()
    if not resolved.is_relative_to(imports_root) or resolved.suffix != ".json":
        raise click.ClickException("Adobe import manifest must be inside Edifice.")
    if not resolved.is_file():
        raise click.ClickException(
            f"Adobe import manifest is unavailable: {manifest_path}"
        )
    return resolved


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(
            f"Cannot read Adobe import manifest: {path}"
        ) from error
    if not isinstance(parsed, dict):
        raise click.ClickException(f"Invalid Adobe import manifest: {path}")
    manifest = cast(dict[str, object], parsed)
    required = {
        "schema_version",
        "manifest_id",
        "created_at",
        "source_system",
        "source_completeness",
        "external_mutation",
        "source_roots",
        "candidate_count",
        "duplicate_source_files",
        "candidates",
    }
    if (
        not required.issubset(manifest)
        or manifest.get("schema_version") != 1
        or manifest.get("source_system") != "adobe-cloud"
        or not isinstance(manifest.get("source_roots"), list)
        or not isinstance(manifest.get("candidates"), list)
    ):
        raise click.ClickException(f"Invalid Adobe import manifest: {path}")
    return manifest


def _manifest_source_roots(manifest: dict[str, object]) -> tuple[Path, ...]:
    roots: list[Path] = []
    for item in cast(list[object], manifest["source_roots"]):
        if not isinstance(item, dict):
            raise click.ClickException("Invalid Adobe source root.")
        root = cast(dict[str, object], item)
        path = root.get("path")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise click.ClickException("Invalid Adobe source root.")
        roots.append(Path(path).resolve())
    return tuple(roots)


def _render_review(manifest: dict[str, object]) -> str:
    completeness = cast(str, manifest["source_completeness"])
    lines = [
        "---",
        "type: adobe-pdf-import-review",
        "schema_version: 1",
        f"manifest_id: {manifest['manifest_id']}",
        f"source_completeness: {completeness}",
        "---",
        "",
        "# Adobe PDF import review",
        "",
        f"- Candidates: `{manifest['candidate_count']}`",
        f"- Duplicate source files: `{manifest['duplicate_source_files']}`",
        f"- Completeness: `{completeness}`",
        "- Adobe mutation: `not-applicable`",
        "",
        "Decisions remain `review` until explicitly approved as personal or skipped.",
        "",
    ]
    for item in cast(list[object], manifest["candidates"]):
        candidate = cast(dict[str, object], item)
        lines.extend(
            [
                f"## {candidate['proposed_filename']}",
                "",
                f"- ID: `{candidate['id']}`",
                f"- Decision: `{candidate['decision']}`",
                f"- Status: `{candidate['status']}`",
                f"- Title: {_safe_markdown(cast(str, candidate['title']))}",
                f"- Creator: {_safe_markdown(cast(str, candidate['creator'])) or 'Unavailable'}",
                f"- Kind: `{candidate['document_kind']}`",
                f"- Confidence: `{candidate['naming_confidence']}`",
                f"- Original filename: `{_safe_code(cast(str, candidate['original_filename']))}`",
                f"- SHA-256: `{candidate['sha256']}`",
                "",
            ]
        )
    return "\n".join(lines)


def _safe_markdown(value: str) -> str:
    return " ".join(value.replace("<", "&lt;").replace(">", "&gt;").split())


def _safe_code(value: str) -> str:
    return _safe_markdown(value).replace("`", "'")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise click.ClickException("Invalid Adobe import year.")
    return value


def _encode_manifest(manifest: dict[str, object]) -> bytes:
    return (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()


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


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
