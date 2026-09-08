import hashlib
import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from edifice.cli import cli
from edifice.pdf_library import PdfMetadata, propose_pdf_naming


def _write_pdf(path: Path, marker: bytes = b"first") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    environment: dict[str, str] | None = None,
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
        env=environment,
    )


def _use_metadata(
    monkeypatch: pytest.MonkeyPatch,
    metadata: PdfMetadata,
) -> None:
    def extract(_: Path) -> PdfMetadata:
        return metadata

    monkeypatch.setattr("edifice.pdf_library.extract_pdf_metadata", extract)


def _propose(
    monkeypatch: pytest.MonkeyPatch,
    metadata: PdfMetadata,
    *,
    original_filename: str = "cached-resource.pdf",
):
    _use_metadata(monkeypatch, metadata)
    return propose_pdf_naming(
        content=b"%PDF-1.7\ncontent\n%%EOF\n",
        original_filename=original_filename,
        document_kind=None,
        title_override=None,
        creator_override=None,
        year_override=None,
        version_override=None,
    )


def test_pdf_naming_joins_split_book_title_and_extracts_author_and_edition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, naming = _propose(
        monkeypatch,
        PdfMetadata(
            title="",
            author="",
            creation_date="Sat Feb 15 2025 13:31:31 GMT-0800",
            first_page_text=(
                "DISTRIBUTED\n"
                "SYSTEMS\n"
                "MAARTEN VAN STEEN\n"
                "ANDREW S. TANENBAUM\n"
                "4TH EDITION VERSION 03"
            ),
            page_count=700,
            evidence_status="verified",
        ),
    )

    assert naming.title == "DISTRIBUTED SYSTEMS"
    assert naming.creator == "Maarten Van Steen et al"
    assert naming.version == "4TH EDITION VERSION 03"
    assert naming.canonical_filename == (
        "maarten-van-steen-et-al-distributed-systems-4th-edition-version-03-2025.pdf"
    )


def test_pdf_naming_skips_license_boilerplate_and_uses_printed_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, naming = _propose(
        monkeypatch,
        PdfMetadata(
            title="",
            author="",
            creation_date="Wed Apr 10 2024 14:11:43 GMT-0700",
            first_page_text=(
                "arXiv:1706.03762v7 [cs.CL] 2 Aug 2023\n"
                "Provided proper attribution is provided, Google hereby grants "
                "permission to\n"
                "reproduce the tables and figures in this paper solely for use in "
                "journalistic or\n"
                "scholarly works.\n"
                "Attention Is All You Need\n"
                "Ashish Vaswani\n"
                "Google Brain\n"
                "avaswani@google.com"
            ),
            page_count=15,
            evidence_status="verified",
        ),
    )

    assert naming.title == "Attention Is All You Need"
    assert naming.creator == "Ashish Vaswani"
    assert naming.year == 2023
    assert naming.document_kind == "research-paper"
    assert naming.canonical_filename == (
        "ashish-vaswani-attention-is-all-you-need-2023.pdf"
    )


def test_pdf_naming_replaces_generic_metadata_title_with_first_page_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, naming = _propose(
        monkeypatch,
        PdfMetadata(
            title="Front Matter",
            author="Schwabish, Jonathan",
            creation_date="Mon Apr 13 2026 21:06:04 GMT-0700",
            first_page_text=(
                "BETTER\n"
                "PRESENTATIONS\n"
                "This content downloaded from\n"
                "\x00\x00\x00128.220.51.130 on Tue, 14 Apr 2026"
            ),
            page_count=300,
            evidence_status="verified",
        ),
    )

    assert naming.title == "BETTER PRESENTATIONS"
    assert naming.creator == "Schwabish, Jonathan"
    assert naming.canonical_filename == (
        "schwabish-jonathan-better-presentations-2026.pdf"
    )


def test_pdf_naming_ignores_affiliations_after_split_research_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, naming = _propose(
        monkeypatch,
        PdfMetadata(
            title="Untitled",
            author="Unknown",
            creation_date="Tue Sep 04 2012 04:37:21 GMT-0700",
            first_page_text=(
                "BMJ 2012;345:e5661 doi: 10.1136/bmj.e5661 "
                "(Published 4 September 2012) Page 1 of 21\n"
                "Research Methods & Reporting\n"
                "RESEARCH METHODS & REPORTING\n"
                "Consort 2010 statement: extension to cluster\n"
                "randomised trials\n"
                "The Consolidated Standards of Reporting Trials statement was "
                "developed to improve reporting.\n"
                "Marion K Campbell director, Gilda Piaggio honorary professor\n"
                "Department of Medical Statistics, London School of Hygiene\n"
                "and Tropical Medicine, London, UK; Centre for Statistics in "
                "Medicine, University of Oxford, Oxford, UK"
            ),
            page_count=21,
            evidence_status="verified",
        ),
    )

    assert naming.title == (
        "Consort 2010 statement: extension to cluster randomised trials"
    )
    assert naming.creator == ""
    assert naming.year == 2012
    assert naming.document_kind == "research-paper"
    assert naming.canonical_filename == (
        "consort-2010-statement-extension-to-cluster-randomised-trials-2012.pdf"
    )


def test_pdf_naming_uses_human_filename_with_verified_author_as_medium_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, naming = _propose(
        monkeypatch,
        PdfMetadata(
            title="",
            author="Remzi Arpaci",
            creation_date="Tue May 24 2016 02:37:51 GMT-0700",
            first_page_text="",
            page_count=700,
            evidence_status="verified",
        ),
        original_filename="Operating Systems - Three Easy Pieces.pdf",
    )

    assert naming.title == "Operating Systems - Three Easy Pieces"
    assert naming.confidence == "medium"
    assert naming.canonical_filename == (
        "remzi-arpaci-operating-systems-three-easy-pieces-2016.pdf"
    )


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


def test_pdf_add_backs_personal_file_to_configured_drive_library(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_metadata(monkeypatch, _metadata())
    source_pdf = _write_pdf(tmp_path / "document.pdf")
    vault_root = tmp_path / "vault"
    drive_library = tmp_path / "My Drive" / "Library"

    result = _invoke_add(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        source_pdf=source_pdf,
        environment={"EDIFICE_PERSONAL_LIBRARY": str(drive_library)},
    )

    drive_pdf = (
        drive_library / "inbox" / "nadia-ahmad-reliable-context-gathering-2026.pdf"
    )
    catalog = json.loads(
        (
            vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
        ).read_text(encoding="utf-8")
    )
    assert result.exit_code == 0
    assert drive_pdf.read_bytes() == source_pdf.read_bytes()
    artifact = catalog["artifacts"][0]
    assert artifact["drive_copy_status"] == "local-hash-verified"
    assert artifact["drive_sync_status"] == "unavailable"
    assert artifact["drive_path"] == (
        "Library/inbox/nadia-ahmad-reliable-context-gathering-2026.pdf"
    )

    catalog_before = (
        vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
    ).read_bytes()
    verified_again = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--personal-library",
            str(drive_library),
            "pdf",
            "backup-personal",
        ],
    )
    catalog_after = (
        vault_root / "10-personal" / "operations" / "artifacts" / "pdf-catalog.json"
    ).read_bytes()
    assert verified_again.exit_code == 0
    assert catalog_after == catalog_before


def test_pdf_backup_refuses_to_overwrite_different_drive_bytes(
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
    drive_library = tmp_path / "My Drive" / "Library"
    drive_pdf = (
        drive_library / "inbox" / "nadia-ahmad-reliable-context-gathering-2026.pdf"
    )
    _write_pdf(drive_pdf, b"different")
    before = drive_pdf.read_bytes()

    backed_up = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--personal-library",
            str(drive_library),
            "pdf",
            "backup-personal",
        ],
    )

    assert backed_up.exit_code != 0
    assert "Refusing to overwrite different Drive bytes" in backed_up.output
    assert drive_pdf.read_bytes() == before
