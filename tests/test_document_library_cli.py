import json
from datetime import UTC, datetime
from pathlib import Path

import click
from click.testing import CliRunner
from pytest import MonkeyPatch

from edifice.cli import cli
from edifice.document_library import DriveDocument


class FakeDocumentSource:
    def __init__(self, documents: tuple[DriveDocument, ...]) -> None:
        self.documents = {document.source_id: document for document in documents}

    def get_document(self, source_id: str) -> DriveDocument:
        return self.documents[source_id]

    def recently_viewed(
        self,
        *,
        days: int,
        limit: int,
    ) -> tuple[DriveDocument, ...]:
        return tuple(self.documents.values())[:limit]


class FailingDocumentSource(FakeDocumentSource):
    def recently_viewed(
        self,
        *,
        days: int,
        limit: int,
    ) -> tuple[DriveDocument, ...]:
        raise click.ClickException("Google Drive is unavailable.")


def _base_arguments(vault_root: Path, audit_root: Path) -> list[str]:
    return [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
    ]


def _create_current_pointer(vault_root: Path) -> None:
    path = vault_root / "00-system/current.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "work": "10-personal/operations/projects/first-deliverable.md",
                "question": (
                    "10-personal/operations/questions/select-first-deliverable.md"
                ),
            }
        )
    )


def _document(
    *,
    source_id: str = "doc-one",
    title: str = "Architecture memo",
    version: str = "7",
) -> DriveDocument:
    return DriveDocument(
        source_id=source_id,
        source_url=f"https://docs.google.com/document/d/{source_id}/edit",
        title=title,
        mime_type="application/vnd.google-apps.document",
        modified_at="2026-09-12T18:30:00Z",
        viewed_at="2026-09-13T06:30:00Z",
        shared_at="2026-09-10T15:00:00Z",
        version=version,
    )


def test_docs_add_direct_link_creates_verified_reading_queue(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    document = _document()
    monkeypatch.setattr(
        "edifice.cli.create_nflx_google_source",
        lambda: FakeDocumentSource((document,)),
    )
    monkeypatch.setattr(
        "edifice.document_library._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "docs",
            "add",
            document.source_url,
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
        ],
    )

    index_path = (
        vault_root / "20-work" / "operations" / "document-library" / "index.json"
    )
    inbox_path = index_path.with_name("inbox.md")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = index["documents"]["doc-one"]

    assert result.exit_code == 0
    assert result.output == (
        "Added document: doc-one.\n"
        "Reading inbox: 20-work/operations/document-library/inbox.md.\n"
    )
    assert record["title"] == "Architecture memo"
    assert record["reading_state"] == "unread"
    assert record["source_version"] == "7"
    assert record["read_version"] is None
    assert record["classification"] == "netflix-internal"
    assert record["review_on"] == "2026-10-01"
    assert "content" not in record
    inbox = inbox_path.read_text(encoding="utf-8")
    assert "[Architecture memo]" in inbox
    assert "`unread`" in inbox


def test_docs_sync_recent_marks_read_document_changed_when_drive_version_advances(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    current_source = FakeDocumentSource(
        (
            _document(source_id="doc-one", version="7"),
            _document(source_id="doc-two", title="Rollout memo", version="3"),
        )
    )
    monkeypatch.setattr(
        "edifice.cli.create_nflx_google_source",
        lambda: current_source,
    )
    monkeypatch.setattr(
        "edifice.document_library._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    base = _base_arguments(vault_root, audit_root)

    synced = runner.invoke(
        cli,
        [
            *base,
            "docs",
            "sync-recent",
            "--days",
            "30",
            "--limit",
            "20",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
        ],
    )
    marked = runner.invoke(
        cli,
        [*base, "docs", "mark", "doc-one", "--state", "read"],
    )
    current_source.documents["doc-one"] = _document(
        source_id="doc-one",
        version="8",
    )
    refreshed = runner.invoke(
        cli,
        [
            *base,
            "docs",
            "sync-recent",
            "--days",
            "30",
            "--limit",
            "20",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
        ],
    )

    index = json.loads(
        (
            vault_root / "20-work" / "operations" / "document-library" / "index.json"
        ).read_text(encoding="utf-8")
    )
    first = index["documents"]["doc-one"]
    second = index["documents"]["doc-two"]

    assert synced.exit_code == 0
    assert synced.output == (
        "Recently viewed: 2.\n"
        "Added: 2; refreshed: 0; changed: 0.\n"
        "Reading inbox: 20-work/operations/document-library/inbox.md.\n"
    )
    assert marked.exit_code == 0
    assert marked.output == "Marked doc-one as read.\n"
    assert refreshed.exit_code == 0
    assert "Added: 0; refreshed: 2; changed: 1." in refreshed.output
    assert first["reading_state"] == "changed"
    assert first["read_version"] == "7"
    assert first["source_version"] == "8"
    assert second["reading_state"] == "unread"


def test_docs_categorize_list_status_and_open_use_local_tracker_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    source = FakeDocumentSource(
        (
            _document(source_id="doc-one"),
            _document(source_id="doc-two", title="Rollout memo"),
        )
    )
    monkeypatch.setattr(
        "edifice.cli.create_nflx_google_source",
        lambda: source,
    )
    monkeypatch.setattr(
        "edifice.document_library._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    base = _base_arguments(vault_root, audit_root)
    assert (
        runner.invoke(
            cli,
            [
                *base,
                "docs",
                "sync-recent",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-10-01",
            ],
        ).exit_code
        == 0
    )

    categorized = runner.invoke(
        cli,
        [
            *base,
            "docs",
            "categorize",
            "https://docs.google.com/document/d/doc-one/edit",
            "--category",
            "Architecture",
        ],
    )
    listed = runner.invoke(cli, [*base, "docs", "list", "--state", "unread"])
    status = runner.invoke(cli, [*base, "docs", "status"])
    opened = runner.invoke(cli, [*base, "--dry-run", "docs", "open"])

    assert categorized.exit_code == 0
    assert categorized.output == "Categorized doc-one as Architecture.\n"
    assert listed.exit_code == 0
    assert "doc-one | unread | Architecture memo | Architecture" in listed.output
    assert "doc-two | unread | Rollout memo | uncategorized" in listed.output
    assert status.exit_code == 0
    assert status.output == (
        "Documents: 2.\nUnread: 2; reading: 0; read: 0; changed: 0; archived: 0.\n"
    )
    assert opened.exit_code == 0
    assert opened.output == (
        "Would open 20-work/operations/document-library/inbox.md in Obsidian.\n"
    )


def test_docs_rejects_invalid_link_and_google_failure_without_partial_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    base = _base_arguments(vault_root, audit_root)

    invalid = runner.invoke(
        cli,
        [
            *base,
            "docs",
            "add",
            "https://example.com/not-google",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
        ],
    )
    monkeypatch.setattr(
        "edifice.cli.create_nflx_google_source",
        lambda: FailingDocumentSource(()),
    )
    failed_sync = runner.invoke(
        cli,
        [
            *base,
            "docs",
            "sync-recent",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
        ],
    )

    index_path = (
        vault_root / "20-work" / "operations" / "document-library" / "index.json"
    )
    assert invalid.exit_code != 0
    assert "Not a supported Google Docs or Drive URL." in invalid.output
    assert failed_sync.exit_code != 0
    assert "Google Drive is unavailable." in failed_sync.output
    assert not index_path.exists()


def test_docs_assigns_filters_and_unassigns_registered_project(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    _create_current_pointer(vault_root)
    document = _document()
    monkeypatch.setattr(
        "edifice.cli.create_nflx_google_source",
        lambda: FakeDocumentSource((document,)),
    )
    runner = CliRunner()
    base = _base_arguments(vault_root, audit_root)
    assert (
        runner.invoke(
            cli,
            [
                *base,
                "project",
                "start",
                "--name",
                "Document intelligence",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-10-01",
            ],
        ).exit_code
        == 0
    )

    added = runner.invoke(
        cli,
        [
            *base,
            "docs",
            "add",
            document.source_url,
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
            "--project",
            "document-intelligence",
        ],
    )
    listed = runner.invoke(
        cli,
        [*base, "docs", "list", "--project", "document-intelligence"],
    )
    unassigned = runner.invoke(
        cli,
        [*base, "docs", "assign", "doc-one", "--unassign"],
    )

    index = json.loads(
        (vault_root / "20-work/operations/document-library/index.json").read_text()
    )
    record = index["documents"]["doc-one"]
    assert added.exit_code == 0
    assert listed.exit_code == 0
    assert "doc-one | unread | Architecture memo" in listed.output
    assert unassigned.exit_code == 0
    assert record["project_ids"] == []
    assert record["reading_state"] == "unread"
