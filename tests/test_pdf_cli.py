import hashlib
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from edifice.cli import cli
from edifice.pdf_library import PdfMetadata


def _write_pdf(path: Path, marker: bytes = b"first") -> Path:
    path.write_bytes(b"%PDF-1.7\n" + marker + b"\n%%EOF\n")
    return path


def _metadata(
    *,
    title: str = "Reliable Context Gathering",
    author: str = "Nadia Ahmad",
    creation_date: str = "D:20260908120000-07'00'",
    first_page_text: str = "Reliable Context Gathering\nNadia Ahmad",
) -> PdfMetadata:
    return PdfMetadata(
        title=title,
        author=author,
        creation_date=creation_date,
        first_page_text=first_page_text,
        page_count=12,
        evidence_status="verified",
    )


def _invoke_add(
    *,
    vault_root: Path,
    audit_root: Path,
    source_pdf: Path,
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
            "add",
            str(source_pdf),
            "--scope",
            "personal",
            "--classification",
            "personal",
            *(extra_arguments or []),
        ],
    )


def _use_metadata(
    monkeypatch: pytest.MonkeyPatch,
    metadata: PdfMetadata,
) -> None:
    def extract(_: Path) -> PdfMetadata:
        return metadata

    monkeypatch.setattr("edifice.pdf_library.extract_pdf_metadata", extract)


def test_pdf_add_uses_content_metadata_for_canonical_kebab_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    source_pdf = _write_pdf(tmp_path / "scan-0042.pdf")
    vault_root = tmp_path / "vault"

    result = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
        extra_arguments=["--kind", "research-paper"],
    )

    stored_pdf = (
        vault_root
        / "10-personal"
        / "artifacts"
        / "pdfs"
        / "papers-and-articles"
        / "nadia-ahmad-reliable-context-gathering-2026.pdf"
    )
    index_path = (
        vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
    )
    assert result.exit_code == 0
    assert stored_pdf.read_bytes() == source_pdf.read_bytes()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["artifacts"]) == 1
    artifact = index["artifacts"][0]
    assert artifact["canonical_filename"] == stored_pdf.name
    assert artifact["original_filename"] == "scan-0042.pdf"
    assert artifact["title"] == "Reliable Context Gathering"
    assert artifact["creator"] == "Nadia Ahmad"
    assert artifact["naming_confidence"] == "high"
    assert artifact["sha256"] == (
        f"sha256:{hashlib.sha256(source_pdf.read_bytes()).hexdigest()}"
    )


def test_pdf_add_requires_authoritative_source_for_work_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    source_pdf = _write_pdf(tmp_path / "work.pdf")

    missing_source = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(tmp_path / "vault"),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "add",
            str(source_pdf),
            "--scope",
            "work",
            "--classification",
            "netflix-internal",
        ],
    )

    assert missing_source.exit_code != 0
    assert "Work PDFs require an authoritative source URL" in missing_source.output

    added = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(tmp_path / "vault"),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "add",
            str(source_pdf),
            "--scope",
            "work",
            "--classification",
            "netflix-internal",
            "--source",
            "https://example.netflix.net/reliable-context-gathering.pdf",
            "--kind",
            "report",
        ],
    )

    stored_pdf = (
        tmp_path
        / "vault"
        / "20-work"
        / "references"
        / "pdfs"
        / "reports-and-official-documents"
        / "nadia-ahmad-reliable-context-gathering-2026.pdf"
    )
    assert added.exit_code == 0
    assert stored_pdf.is_file()


def test_pdf_add_deduplicates_identical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    first_pdf = _write_pdf(tmp_path / "first.pdf")
    second_pdf = _write_pdf(tmp_path / "second.pdf")
    vault_root = tmp_path / "vault"

    first = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=first_pdf,
    )
    second = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=second_pdf,
    )

    index_path = (
        vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
    )
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert second.output.startswith("Already cataloged")
    assert len(index["artifacts"]) == 1


def test_pdf_add_uses_hash_suffix_for_same_name_with_different_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    first_pdf = _write_pdf(tmp_path / "first.pdf", b"first")
    second_pdf = _write_pdf(tmp_path / "second.pdf", b"second")
    vault_root = tmp_path / "vault"

    first = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=first_pdf,
    )
    second = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=second_pdf,
    )

    stored_files = sorted(
        (vault_root / "10-personal" / "artifacts" / "pdfs" / "inbox").glob("*.pdf")
    )
    second_hash = hashlib.sha256(second_pdf.read_bytes()).hexdigest()
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert len(stored_files) == 2
    assert any(path.stem.endswith(second_hash[:8]) for path in stored_files)
    assert {path.read_bytes() for path in stored_files} == {
        first_pdf.read_bytes(),
        second_pdf.read_bytes(),
    }


def test_pdf_add_requires_confirmation_for_low_confidence_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(
        monkeypatch,
        _metadata(
            title="",
            author="",
            creation_date="",
            first_page_text="",
        ),
    )
    source_pdf = _write_pdf(tmp_path / "mystery-file.pdf")

    rejected = _invoke_add(
        vault_root=tmp_path / "vault",
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
    )
    accepted = _invoke_add(
        vault_root=tmp_path / "vault",
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
        extra_arguments=["--accept-name"],
    )

    assert rejected.exit_code != 0
    assert "low confidence" in rejected.output
    assert "--accept-name" in rejected.output
    assert accepted.exit_code == 0
    assert "mystery-file.pdf" in accepted.output


def test_pdf_add_title_override_controls_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(
        monkeypatch,
        _metadata(title="", first_page_text="Unhelpful scan"),
    )
    source_pdf = _write_pdf(tmp_path / "scan.pdf")

    result = _invoke_add(
        vault_root=tmp_path / "vault",
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
        extra_arguments=[
            "--title",
            "A Better Name",
            "--creator",
            "Research Group",
            "--year",
            "2025",
            "--kind",
            "report",
        ],
    )

    expected = (
        tmp_path
        / "vault"
        / "10-personal"
        / "artifacts"
        / "pdfs"
        / "reports-and-official-documents"
        / "research-group-a-better-name-2025.pdf"
    )
    assert result.exit_code == 0
    assert expected.is_file()


def test_pdf_inventory_verifies_cataloged_files_and_detects_changed_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    source_pdf = _write_pdf(tmp_path / "document.pdf")
    vault_root = tmp_path / "vault"
    added = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
    )
    assert added.exit_code == 0

    healthy = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "inventory",
        ],
    )
    stored_pdf = next((vault_root / "10-personal" / "artifacts").rglob("*.pdf"))
    stored_pdf.write_bytes(b"%PDF-1.7\nchanged\n%%EOF\n")
    changed = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "pdf",
            "inventory",
        ],
    )

    assert healthy.exit_code == 0
    assert "1 verified, 0 unavailable, 0 mismatched" in healthy.output
    assert changed.exit_code != 0
    assert (
        "[mismatched] "
        "10-personal/artifacts/pdfs/inbox/"
        "nadia-ahmad-reliable-context-gathering-2026.pdf"
    ) in changed.output
    assert "0 verified, 0 unavailable, 1 mismatched" in changed.output


def test_pdf_add_rolls_back_new_file_when_catalog_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    source_pdf = _write_pdf(tmp_path / "document.pdf")
    vault_root = tmp_path / "vault"

    real_replace = os.replace

    def fail_markdown_catalog(source: str | Path, target: str | Path) -> None:
        if Path(target).name == "pdf-catalog.md":
            raise OSError("controlled catalog failure")
        real_replace(source, target)

    monkeypatch.setattr(
        "edifice.pdf_library.os.replace",
        fail_markdown_catalog,
    )

    result = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
    )

    assert result.exit_code != 0
    assert not list((vault_root / "10-personal").rglob("*.pdf"))
    assert not (
        vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
    ).exists()
