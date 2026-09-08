import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import click

from edifice.identifiers import new_uuid7

MIGRATION_NAMESPACE = uuid.UUID("b8415247-209f-4fc8-b4b6-b6b119661222")


@dataclass(frozen=True)
class MigrationInventoryResult:
    package_path: Path
    file_count: int
    directory_count: int
    total_bytes: int


@dataclass(frozen=True)
class MigrationPlanResult:
    package_path: Path
    item_count: int
    markdown_count: int


@dataclass(frozen=True)
class MigrationVerification:
    verified: int
    unavailable: int
    mismatched: int
    issues: tuple[str, ...]


def inventory_obsidian_vault(
    *,
    source_vault: Path,
    migrations_root: Path,
    vault_root: Path,
    audit_root: Path,
) -> MigrationInventoryResult:
    """Create a complete local read-only snapshot of an Obsidian vault."""
    return inventory_source_directory(
        source_kind="obsidian",
        source_path=source_vault,
        migrations_root=migrations_root,
        vault_root=vault_root,
        audit_root=audit_root,
    )


def inventory_source_directory(
    *,
    source_kind: str,
    source_path: Path,
    migrations_root: Path,
    vault_root: Path,
    audit_root: Path,
) -> MigrationInventoryResult:
    """Create a complete local snapshot for a supported personal source."""
    if source_kind not in {"obsidian", "craft", "coda"}:
        raise click.ClickException(f"Unsupported migration source: {source_kind}")
    source = _validate_source_directory(source_path, migrations_root, vault_root)
    source_name = f"{source_kind}-personal"
    package_parent = migrations_root.expanduser().resolve() / source_name
    package_parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC)
    package_name = f"{timestamp.strftime('%Y-%m-%d-%H%M%S')}-{str(new_uuid7())[:8]}"
    temporary_package = package_parent / f".{package_name}.tmp"
    package_path = package_parent / package_name
    raw_root = temporary_package / "raw"
    raw_root.mkdir(parents=True)

    try:
        directories, files = _snapshot_tree(source, raw_root)
        aggregate_hash = _inventory_hash(files)
        total_bytes = sum(cast(int, item["size_bytes"]) for item in files)
        inventory: dict[str, object] = {
            "schema_version": 1,
            "source_kind": source_kind,
            "source_path": str(source),
            "file_count": len(files),
            "directory_count": len(directories),
            "total_bytes": total_bytes,
            "aggregate_sha256": aggregate_hash,
            "directories": directories,
            "files": files,
        }
        manifest: dict[str, object] = {
            "schema_version": 1,
            "package_id": f"migration-{new_uuid7()}",
            "created_at": timestamp.isoformat(),
            "profile": "personal",
            "source_kind": source_kind,
            "source_path": str(source),
            "status": "inventory-complete",
            "storage": "local-machine-only",
            "encryption_status": "unavailable",
            "external_mutation": False,
            "inventory_sha256": _json_hash(inventory),
            "aggregate_sha256": aggregate_hash,
        }
        validation: dict[str, object] = {
            "schema_version": 1,
            "verified_at": timestamp.isoformat(),
            "evidence_status": "verified",
            "verified_files": len(files),
            "unavailable_files": 0,
            "mismatched_files": 0,
            "source_unchanged": True,
        }
        (temporary_package / "proposed").mkdir()
        _write_json(temporary_package / "inventory.json", inventory)
        _write_json(temporary_package / "manifest.json", manifest)
        _write_json(temporary_package / "validation.json", validation)
        _replace_atomically(
            temporary_package / "report.md",
            _inventory_report(manifest, inventory).encode(),
        )
        os.replace(temporary_package, package_path)
    except Exception:
        shutil.rmtree(temporary_package, ignore_errors=True)
        raise

    _write_migration_cockpit(
        vault_root=vault_root,
        package_path=package_path,
        source_kind=source_kind,
        status="inventory-complete",
        file_count=len(files),
        markdown_count=None,
    )
    _append_migration_audit(
        audit_root=audit_root,
        event_type="migration.inventory-complete",
        package_path=package_path,
        file_count=len(files),
        aggregate_hash=aggregate_hash,
    )
    return MigrationInventoryResult(
        package_path=package_path,
        file_count=len(files),
        directory_count=len(directories),
        total_bytes=total_bytes,
    )


def plan_migration(
    *,
    package_path: Path,
    migrations_root: Path,
    vault_root: Path,
) -> MigrationPlanResult:
    """Create review-only routing proposals from a verified snapshot."""
    package = _validate_package_path(package_path, migrations_root)
    verification = verify_migration_package(
        package_path=package,
        migrations_root=migrations_root,
    )
    if verification.unavailable or verification.mismatched:
        raise click.ClickException("Migration package verification failed.")
    manifest = _load_json_object(package / "manifest.json")
    inventory = _load_json_object(package / "inventory.json")
    source_kind = cast(str, manifest["source_kind"])
    items: list[dict[str, object]] = []
    markdown_count = 0
    for entry in cast(list[object], inventory["files"]):
        file_entry = cast(dict[str, object], entry)
        relative_path = Path(cast(str, file_entry["path"]))
        raw_path = package / "raw" / relative_path
        if relative_path.suffix.casefold() in {".md", ".markdown", ".txt"}:
            if relative_path.suffix.casefold() in {".md", ".markdown"}:
                markdown_count += 1
            item = _plan_text_item(
                raw_path,
                relative_path,
                file_entry,
                source_kind,
            )
        else:
            item = _plan_attachment_item(relative_path, file_entry, source_kind)
        items.append(item)
    _disambiguate_targets(items)
    candidate_counts = _candidate_counts(items)
    work_source_count = candidate_counts.get("work-source", 0)
    mapping: dict[str, object] = {
        "schema_version": 1,
        "package_id": manifest["package_id"],
        "created_at": datetime.now(UTC).isoformat(),
        "status": "review",
        "item_count": len(items),
        "markdown_count": markdown_count,
        "decision_counts": {"review": len(items)},
        "candidate_counts": candidate_counts,
        "items": items,
    }
    _write_json(package / "mapping.json", mapping)
    manifest["status"] = "planned"
    manifest["mapping_sha256"] = _json_hash(mapping)
    manifest["contains_work_content_candidates"] = work_source_count > 0
    manifest["local_migration_status"] = "review-allowed"
    manifest["cloud_storage_status"] = (
        "policy-blocked" if work_source_count else "unavailable"
    )
    _write_json(package / "manifest.json", manifest)
    _replace_atomically(
        package / "report.md",
        _plan_report(manifest, inventory, mapping).encode(),
    )
    _write_migration_cockpit(
        vault_root=vault_root,
        package_path=package,
        source_kind=source_kind,
        status="planned",
        file_count=cast(int, inventory["file_count"]),
        markdown_count=markdown_count,
    )
    return MigrationPlanResult(
        package_path=package,
        item_count=len(items),
        markdown_count=markdown_count,
    )


def verify_migration_package(
    *,
    package_path: Path,
    migrations_root: Path,
) -> MigrationVerification:
    """Verify raw snapshot bytes against the package inventory."""
    package = _validate_package_path(package_path, migrations_root)
    inventory = _load_json_object(package / "inventory.json")
    verified = 0
    unavailable = 0
    mismatched = 0
    issues: list[str] = []
    expected_paths: set[Path] = set()
    files = cast(list[object], inventory.get("files"))
    for entry in files:
        file_entry = cast(dict[str, object], entry)
        relative_path = Path(cast(str, file_entry["path"]))
        expected_paths.add(relative_path)
        raw_path = package / "raw" / relative_path
        if not raw_path.is_file():
            unavailable += 1
            issues.append(f"[unavailable] {relative_path.as_posix()}")
            continue
        if _sha256(raw_path.read_bytes()) != file_entry["sha256"]:
            mismatched += 1
            issues.append(f"[mismatched] {relative_path.as_posix()}")
            continue
        if raw_path.stat().st_mode & stat.S_IWUSR:
            mismatched += 1
            issues.append(f"[writable] {relative_path.as_posix()}")
            continue
        verified += 1
    actual_paths = {
        path.relative_to(package / "raw")
        for path in (package / "raw").rglob("*")
        if path.is_file()
    }
    for extra in sorted(actual_paths - expected_paths):
        mismatched += 1
        issues.append(f"[unexpected] {extra.as_posix()}")
    if _inventory_hash(cast(list[dict[str, object]], files)) != inventory.get(
        "aggregate_sha256"
    ):
        mismatched += 1
        issues.append("[mismatched] inventory aggregate")
    return MigrationVerification(
        verified=verified,
        unavailable=unavailable,
        mismatched=mismatched,
        issues=tuple(issues),
    )


def migration_status(migrations_root: Path) -> list[dict[str, object]]:
    """List migration packages from their manifests."""
    root = migrations_root.expanduser().resolve()
    if not root.exists():
        return []
    packages: list[dict[str, object]] = []
    for manifest_path in sorted(root.glob("*/*/manifest.json")):
        try:
            manifest = _load_json_object(manifest_path)
        except click.ClickException:
            continue
        packages.append(
            {
                "source": manifest.get("source_kind", "unavailable"),
                "profile": manifest.get("profile", "unavailable"),
                "status": manifest.get("status", "unavailable"),
                "package_id": manifest.get("package_id", "unavailable"),
                "path": str(manifest_path.parent),
            }
        )
    return packages


def _validate_source_directory(
    source_vault: Path,
    migrations_root: Path,
    vault_root: Path,
) -> Path:
    if not source_vault.is_absolute():
        raise click.ClickException("Migration source path must be absolute.")
    source = source_vault.expanduser().resolve()
    if not source.is_dir():
        raise click.ClickException(f"Migration source is unavailable: {source_vault}")
    migrations = migrations_root.expanduser().resolve()
    live_vault = vault_root.expanduser().resolve()
    if migrations.is_relative_to(source) or source.is_relative_to(migrations):
        raise click.ClickException(
            "Migration source and package root must be separate."
        )
    if source == live_vault:
        raise click.ClickException("The live Edifice vault cannot be its own source.")
    return source


def _snapshot_tree(
    source: Path,
    raw_root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    directories: list[dict[str, object]] = [
        {"path": ".", "source_mode": stat.S_IMODE(source.stat().st_mode)}
    ]
    files: list[dict[str, object]] = []
    for root, directory_names, file_names in os.walk(source, followlinks=False):
        root_path = Path(root)
        directory_names.sort()
        file_names.sort()
        for directory_name in tuple(directory_names):
            source_directory = root_path / directory_name
            if source_directory.is_symlink():
                raise click.ClickException(
                    f"Symlinks are not supported: {source_directory}"
                )
            relative_directory = source_directory.relative_to(source)
            (raw_root / relative_directory).mkdir(parents=True, exist_ok=True)
            directories.append(
                {
                    "path": relative_directory.as_posix(),
                    "source_mode": stat.S_IMODE(source_directory.stat().st_mode),
                }
            )
        for file_name in file_names:
            source_file = root_path / file_name
            if source_file.is_symlink():
                raise click.ClickException(f"Symlinks are not supported: {source_file}")
            if not source_file.is_file():
                raise click.ClickException(
                    f"Unsupported migration source file: {source_file}"
                )
            relative_file = source_file.relative_to(source)
            before = source_file.stat()
            content = source_file.read_bytes()
            after = source_file.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise click.ClickException(
                    f"Source changed during migration inventory: {relative_file}"
                )
            source_hash = _sha256(content)
            destination = raw_root / relative_file
            _write_raw_file(destination, content, before.st_mtime_ns)
            if _sha256(destination.read_bytes()) != source_hash:
                raise click.ClickException(f"Snapshot hash mismatch: {relative_file}")
            if _sha256(source_file.read_bytes()) != source_hash:
                raise click.ClickException(
                    f"Source changed during migration inventory: {relative_file}"
                )
            files.append(
                {
                    "path": relative_file.as_posix(),
                    "size_bytes": len(content),
                    "modified_ns": before.st_mtime_ns,
                    "source_mode": stat.S_IMODE(before.st_mode),
                    "sha256": source_hash,
                }
            )
    for directory in sorted(
        (path for path in raw_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    raw_root.chmod(0o500)
    return directories, files


def _write_raw_file(path: Path, content: bytes, modified_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("Migration snapshot write made no progress.")
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(descriptor)
    os.utime(path, ns=(modified_ns, modified_ns))
    path.chmod(0o400)


def _plan_text_item(
    raw_path: Path,
    relative_path: Path,
    file_entry: dict[str, object],
    source_kind: str,
) -> dict[str, object]:
    try:
        content = raw_path.read_text(encoding="utf-8")
        evidence = "verified"
    except UnicodeDecodeError:
        content = ""
        evidence = "unavailable"
    title = _markdown_title(content, relative_path.stem)
    task_count = len(re.findall(r"(?m)^\s*-\s+\[[ xX]\]\s+", content))
    wiki_link_count = len(re.findall(r"\[\[[^\]]+\]\]", content))
    external_link_count = len(re.findall(r"https?://\S+", content))
    word_count = len(re.findall(r"\b[\w'-]+\b", content, flags=re.UNICODE))
    candidate_type, proposed_target, confidence, reasons = _propose_note_route(
        relative_path=relative_path,
        title=title,
        task_count=task_count,
    )
    return {
        "source_id": _source_id(
            source_kind,
            relative_path,
            cast(str, file_entry["sha256"]),
        ),
        "source_path": relative_path.as_posix(),
        "source_sha256": file_entry["sha256"],
        "title": title,
        "candidate_type": candidate_type,
        "proposed_target": proposed_target,
        "confidence": confidence,
        "decision": "review",
        "evidence_status": evidence,
        "task_count": task_count,
        "wiki_link_count": wiki_link_count,
        "external_link_count": external_link_count,
        "word_count": word_count,
        "reasons": reasons,
    }


def _plan_attachment_item(
    relative_path: Path,
    file_entry: dict[str, object],
    source_kind: str,
) -> dict[str, object]:
    top_level = relative_path.parts[0].casefold() if relative_path.parts else ""
    if relative_path.parts and relative_path.parts[0] == ".obsidian":
        return {
            "source_id": _source_id(
                source_kind,
                relative_path,
                cast(str, file_entry["sha256"]),
            ),
            "source_path": relative_path.as_posix(),
            "source_sha256": file_entry["sha256"],
            "title": relative_path.name,
            "candidate_type": "configuration",
            "proposed_target": None,
            "confidence": "high",
            "decision": "review",
            "evidence_status": "verified",
            "reasons": ["Obsidian configuration remains preserved in the raw package."],
        }
    if top_level in {"netflix", "work", "work notes"}:
        return {
            "source_id": _source_id(
                source_kind,
                relative_path,
                cast(str, file_entry["sha256"]),
            ),
            "source_path": relative_path.as_posix(),
            "source_sha256": file_entry["sha256"],
            "title": relative_path.name,
            "candidate_type": "work-source",
            "proposed_target": (
                Path("20-work/references/imported")
                / _kebab_filename(relative_path.name)
            ).as_posix(),
            "confidence": "high",
            "decision": "review",
            "evidence_status": "verified",
            "reasons": [
                (
                    "Legacy work-scoped material may migrate to governed local "
                    "work references after owner review."
                )
            ],
        }
    if top_level in {"readwise", "_sources", "sources"}:
        return {
            "source_id": _source_id(
                source_kind,
                relative_path,
                cast(str, file_entry["sha256"]),
            ),
            "source_path": relative_path.as_posix(),
            "source_sha256": file_entry["sha256"],
            "title": relative_path.name,
            "candidate_type": "source-artifact",
            "proposed_target": (
                Path("10-personal/sources/imported")
                / _kebab_filename(relative_path.name)
            ).as_posix(),
            "confidence": "medium",
            "decision": "review",
            "evidence_status": "verified",
            "reasons": ["Imported source media remains separate from human knowledge."],
        }
    candidate_type = (
        "table-artifact"
        if relative_path.suffix.casefold() in {".csv", ".tsv"}
        else "artifact"
    )
    return {
        "source_id": _source_id(
            source_kind,
            relative_path,
            cast(str, file_entry["sha256"]),
        ),
        "source_path": relative_path.as_posix(),
        "source_sha256": file_entry["sha256"],
        "title": relative_path.name,
        "candidate_type": candidate_type,
        "proposed_target": (
            Path("10-personal/artifacts/imported") / _kebab_filename(relative_path.name)
        ).as_posix(),
        "confidence": "low",
        "decision": "review",
        "evidence_status": "verified",
        "reasons": [
            (
                "Structured table export requires table and schema review."
                if candidate_type == "table-artifact"
                else "Non-text attachment requires artifact review."
            )
        ],
    }


def _propose_note_route(
    *,
    relative_path: Path,
    title: str,
    task_count: int,
) -> tuple[str, str | None, str, list[str]]:
    lower_path = relative_path.as_posix().casefold()
    top_level = relative_path.parts[0].casefold() if relative_path.parts else ""
    filename = _kebab_filename(relative_path.name)
    if relative_path.parts and relative_path.parts[0] == ".obsidian":
        return (
            "configuration",
            None,
            "high",
            ["Obsidian configuration remains preserved in the raw package."],
        )
    if top_level in {"netflix", "work", "work notes"}:
        return (
            "work-source",
            f"20-work/references/imported/{filename}",
            "high",
            [
                (
                    "Legacy work-scoped material may migrate to governed local "
                    "work references after owner review."
                )
            ],
        )
    if top_level in {"readwise", "_sources", "sources"}:
        return (
            "source-note",
            f"10-personal/sources/imported/{filename}",
            "medium",
            ["Imported source material remains separate from human knowledge."],
        )
    if (
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", relative_path.stem)
        or "journal" in lower_path
        or "daily" in lower_path
    ):
        return (
            "journal",
            f"10-personal/notes/journal/{filename}",
            "medium",
            ["Date or journal path suggests protected personal writing."],
        )
    if "project" in lower_path:
        return (
            "project",
            f"10-personal/operations/projects/{filename}",
            "medium",
            ["Source path explicitly identifies a project."],
        )
    if "goal" in lower_path or "outcome" in lower_path:
        return (
            "outcome",
            f"10-personal/operations/outcomes/{filename}",
            "medium",
            ["Source path suggests a goal or measurable outcome."],
        )
    if "question" in lower_path or title.endswith("?"):
        return (
            "question",
            f"10-personal/operations/questions/{filename}",
            "medium",
            ["Source path or title identifies a persistent question candidate."],
        )
    if task_count:
        return (
            "operational-note",
            f"10-personal/operations/imported/{filename}",
            "low",
            ["Checkboxes indicate operational content requiring owner review."],
        )
    return (
        "knowledge",
        f"10-personal/notes/imported/{filename}",
        "low",
        ["General Markdown defaults to a protected knowledge candidate."],
    )


def _disambiguate_targets(items: list[dict[str, object]]) -> None:
    by_target: dict[str, list[dict[str, object]]] = {}
    for item in items:
        target = item.get("proposed_target")
        if isinstance(target, str):
            by_target.setdefault(target, []).append(item)
    for target, duplicates in by_target.items():
        if len(duplicates) < 2:
            continue
        target_path = Path(target)
        for item in duplicates:
            source_hash = cast(str, item["source_sha256"]).split(":", 1)[1]
            item["proposed_target"] = target_path.with_stem(
                f"{target_path.stem}-{source_hash[:8]}"
            ).as_posix()
            reasons = cast(list[str], item["reasons"])
            reasons.append("A deterministic hash suffix avoids a target collision.")


def _candidate_counts(items: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        candidate_type = cast(str, item["candidate_type"])
        counts[candidate_type] = counts.get(candidate_type, 0) + 1
    return dict(sorted(counts.items()))


def _markdown_title(content: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", content)
    if not match:
        return fallback
    return " ".join(match.group(1).split())


def _source_id(source_kind: str, relative_path: Path, source_hash: str) -> str:
    value = f"{source_kind}:{relative_path.as_posix()}:{source_hash}"
    return f"source-{uuid.uuid5(MIGRATION_NAMESPACE, value)}"


def _kebab_filename(filename: str) -> str:
    suffix = Path(filename).suffix.casefold()
    stem = Path(filename).stem
    normalized = unicodedata.normalize("NFKC", stem).casefold()
    kebab = re.sub(r"[\W_]+", "-", normalized, flags=re.UNICODE).strip("-")
    return f"{kebab or 'untitled'}{suffix}"


def _validate_package_path(package_path: Path, migrations_root: Path) -> Path:
    if not package_path.is_absolute():
        raise click.ClickException("Migration package path must be absolute.")
    package = package_path.expanduser().resolve()
    root = migrations_root.expanduser().resolve()
    if not package.is_relative_to(root) or not package.is_dir():
        raise click.ClickException(f"Invalid migration package: {package_path}")
    for required in ("manifest.json", "inventory.json", "raw"):
        if not (package / required).exists():
            raise click.ClickException(f"Migration package is incomplete: {required}")
    return package


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read migration record: {path}") from error
    if not isinstance(value, dict):
        raise click.ClickException(f"Invalid migration record: {path}")
    return cast(dict[str, object], value)


def _inventory_hash(files: list[dict[str, object]]) -> str:
    records = [
        {
            "path": item["path"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
        }
        for item in files
    ]
    return _sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )


def _json_hash(value: dict[str, object]) -> str:
    return _sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )


def _write_json(path: Path, value: dict[str, object]) -> None:
    _replace_atomically(
        path,
        (
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode(),
    )


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


def _write_migration_cockpit(
    *,
    vault_root: Path,
    package_path: Path,
    source_kind: str,
    status: str,
    file_count: int,
    markdown_count: int | None,
) -> None:
    markdown_line = (
        f"- Markdown notes: `{markdown_count}`\n" if markdown_count is not None else ""
    )
    if status == "planned":
        next_steps = f"""Review:

`{package_path / "mapping.json"}`

Then verify:

```text
edifice migrate verify {package_path}
```"""
    else:
        next_steps = f"""```text
edifice migrate plan {package_path}
edifice migrate verify {package_path}
```"""
    content = f"""---
type: migration-home
schema_version: 1
created: {datetime.now(UTC).date().isoformat()}
---

# Migrations

## Current package

- Source: `{source_kind}`
- Status: `{status}`
- Package: `{package_path}`
- Files: `{file_count}`
{markdown_line}
## Next

{next_steps}

No source account or live note has been changed.
"""
    _replace_atomically(
        vault_root / "10-personal" / "operations" / "migrations" / "home.md",
        content.encode(),
    )


def _inventory_report(
    manifest: dict[str, object],
    inventory: dict[str, object],
) -> str:
    return f"""# Obsidian migration package

- Status: `inventory-complete`
- Evidence: `verified`
- Source: `{manifest["source_path"]}`
- Files: `{inventory["file_count"]}`
- Directories: `{inventory["directory_count"]}`
- Bytes: `{inventory["total_bytes"]}`
- Aggregate SHA-256: `{inventory["aggregate_sha256"]}`
- Storage: `local-machine-only`
- Encryption: `unavailable`
- Source mutation: `not-applicable`

No live-vault material has been created.
"""


def _plan_report(
    manifest: dict[str, object],
    inventory: dict[str, object],
    mapping: dict[str, object],
) -> str:
    return f"""# Obsidian migration package

- Status: `planned`
- Evidence: `verified`
- Source: `{manifest["source_path"]}`
- Files: `{inventory["file_count"]}`
- Markdown notes: `{mapping["markdown_count"]}`
- Proposed items: `{mapping["item_count"]}`
- Work-source candidates: `{cast(dict[str, int], mapping["candidate_counts"]).get("work-source", 0)}`
- Local migration: `review-allowed`
- Personal cloud: `{manifest["cloud_storage_status"]}`
- Decisions approved: `0`
- Source mutation: `not-applicable`
- Live-vault import: `not-applicable`

Every proposed mapping remains `review`.
"""


def _append_migration_audit(
    *,
    audit_root: Path,
    event_type: str,
    package_path: Path,
    file_count: int,
    aggregate_hash: str,
) -> None:
    audit_root.mkdir(parents=True, exist_ok=True)
    audit_path = audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "personal",
        "event_type": event_type,
        "package": str(package_path),
        "file_count": file_count,
        "aggregate_sha256": aggregate_hash,
        "source_mutation": False,
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


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
