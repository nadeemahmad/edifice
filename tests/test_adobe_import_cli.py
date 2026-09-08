import hashlib
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from edifice.cli import cli
from edifice.pdf_library import PdfMetadata


def _write_pdf(path: Path, marker: bytes = b"content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + marker + b"\n%%EOF\n")
    return path


def _use_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def extract(_: Path) -> PdfMetadata:
        return PdfMetadata(
            title="Distributed Systems",
            author="Maarten van Steen",
            creation_date="D:20240101000000Z",
            first_page_text="Distributed Systems\nMaarten van Steen",
            page_count=640,
            evidence_status="verified",
        )

    monkeypatch.setattr("edifice.pdf_library.extract_pdf_metadata", extract)


def _plan(
    *,
    vault_root: Path,
    audit_root: Path,
    cache_roots: list[Path],
    extra_arguments: list[str] | None = None,
):
    return CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "pdf",
            "import-adobe",
            "plan",
            *(extra_arguments or []),
        ],
        env={
            "EDIFICE_ADOBE_CACHE_ROOTS": os.pathsep.join(
                str(path) for path in cache_roots
            )
        },
    )


def _manifest_path(vault_root: Path) -> Path:
    manifests = list(
        (vault_root / "10-personal" / "operations" / "artifacts" / "imports").glob(
            "adobe-cloud-*.json"
        )
    )
    assert len(manifests) == 1
    return manifests[0]


def test_adobe_plan_discovers_pdf_magic_deduplicates_and_writes_review_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch)
    first_root = tmp_path / "cache-one"
    second_root = tmp_path / "cache-two"
    first_pdf = _write_pdf(first_root / "opaque-resource")
    _write_pdf(second_root / "distributed-systems.pdf")
    (first_root / "not-a-pdf.txt").write_text("not a PDF", encoding="utf-8")
    vault_root = tmp_path / "vault"

    result = _plan(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        cache_roots=[first_root, second_root],
    )

    manifest_path = _manifest_path(vault_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert manifest["source_completeness"] == "trial-required"
    assert manifest["candidate_count"] == 1
    assert manifest["duplicate_source_files"] == 1
    candidate = manifest["candidates"][0]
    assert candidate["decision"] == "review"
    assert candidate["sha256"] == (
        f"sha256:{hashlib.sha256(first_pdf.read_bytes()).hexdigest()}"
    )
    assert candidate["proposed_filename"] == (
        "maarten-van-steen-distributed-systems-2024.pdf"
    )
    assert len(candidate["source_paths"]) == 2
    assert manifest_path.with_suffix(".md").is_file()
    assert not list((vault_root / "10-personal" / "artifacts").rglob("*.pdf"))


def test_adobe_apply_requires_incomplete_source_and_personal_scope_confirmations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch)
    cache_root = tmp_path / "cache"
    _write_pdf(cache_root / "cloud-document.pdf")
    vault_root = tmp_path / "vault"
    planned = _plan(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        cache_roots=[cache_root],
    )
    assert planned.exit_code == 0
    manifest_path = _manifest_path(vault_root)

    incomplete = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "import-adobe",
            "apply",
            str(manifest_path),
            "--confirm-all-personal",
        ],
    )
    pending = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "import-adobe",
            "apply",
            str(manifest_path),
            "--allow-incomplete-source",
        ],
    )

    assert incomplete.exit_code != 0
    assert "--allow-incomplete-source" in incomplete.output
    assert pending.exit_code != 0
    assert "--confirm-all-personal" in pending.output
    assert not list((vault_root / "10-personal" / "artifacts").rglob("*.pdf"))


def test_adobe_apply_imports_confirmed_files_and_preserves_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch)
    cache_root = tmp_path / "cache"
    source_pdf = _write_pdf(cache_root / "cloud-document.pdf")
    source_before = source_pdf.read_bytes()
    vault_root = tmp_path / "vault"
    planned = _plan(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        cache_roots=[cache_root],
    )
    assert planned.exit_code == 0
    manifest_path = _manifest_path(vault_root)

    applied = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "import-adobe",
            "apply",
            str(manifest_path),
            "--allow-incomplete-source",
            "--confirm-all-personal",
        ],
    )

    stored_pdf = (
        vault_root
        / "10-personal"
        / "artifacts"
        / "pdfs"
        / "inbox"
        / "maarten-van-steen-distributed-systems-2024.pdf"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog = json.loads(
        (
            vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
        ).read_text(encoding="utf-8")
    )
    assert applied.exit_code == 0
    assert stored_pdf.read_bytes() == source_before
    assert source_pdf.read_bytes() == source_before
    assert manifest["candidates"][0]["status"] == "imported"
    assert manifest["candidates"][0]["storage_path"] == str(
        stored_pdf.relative_to(vault_root)
    )
    assert catalog["artifacts"][0]["source_system"] == "adobe-cloud"


def test_adobe_apply_rejects_source_changed_after_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch)
    cache_root = tmp_path / "cache"
    source_pdf = _write_pdf(cache_root / "cloud-document.pdf")
    vault_root = tmp_path / "vault"
    planned = _plan(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        cache_roots=[cache_root],
    )
    assert planned.exit_code == 0
    manifest_path = _manifest_path(vault_root)
    source_pdf.write_bytes(b"%PDF-1.7\nchanged after plan\n%%EOF\n")

    applied = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "import-adobe",
            "apply",
            str(manifest_path),
            "--allow-incomplete-source",
            "--confirm-all-personal",
        ],
    )

    assert applied.exit_code != 0
    assert "changed after the Adobe import plan" in applied.output
    assert not list((vault_root / "10-personal" / "artifacts").rglob("*.pdf"))


def test_adobe_export_complete_removes_incomplete_source_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch)
    cache_root = tmp_path / "empty-cache"
    cache_root.mkdir()
    export_root = tmp_path / "adobe-export"
    _write_pdf(export_root / "distributed-systems.pdf")
    vault_root = tmp_path / "vault"

    planned = _plan(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        cache_roots=[cache_root],
        extra_arguments=[
            "--export-dir",
            str(export_root),
            "--export-complete",
        ],
    )
    assert planned.exit_code == 0
    manifest_path = _manifest_path(vault_root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    applied = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "import-adobe",
            "apply",
            str(manifest_path),
            "--confirm-all-personal",
        ],
    )

    assert manifest["source_completeness"] == "owner-attested"
    assert applied.exit_code == 0
