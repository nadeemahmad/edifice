import json
from datetime import date
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from edifice.cli import cli


def test_meeting_start_creates_and_opens_human_owned_work_note(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    relative_path = Path("20-work/notes/meetings/2026-09-09-architecture-sync.md")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "meeting",
            "start",
            "--title",
            "Architecture sync",
            "--scope",
            "work",
            "--classification",
            "netflix-internal",
            "--held-on",
            "2026-09-09",
        ],
    )

    note = (vault_root / relative_path).read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert result.output == (
        f"Created meeting note: {relative_path}.\n"
        f"Would open {relative_path} in Obsidian.\n"
    )
    assert "type: meeting-note" in note
    assert "ownership: human" in note
    assert "scope: work" in note
    assert 'classification: "netflix-internal"' in note
    assert "meeting_on: 2026-09-09" in note
    assert "# Architecture sync" in note
    assert "## Attendees" in note
    assert "## Notes" in note
    assert "## Decisions" in note
    assert "## Action items" in note
    assert "## Open questions" in note
    assert "## Follow-up" in note


def test_meeting_start_records_redacted_audit_evidence(tmp_path: Path) -> None:
    audit_root = tmp_path / "audit"

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(tmp_path / "vault"),
            "--audit-root",
            str(audit_root),
            "--dry-run",
            "meeting",
            "start",
            "--title",
            "Private planning discussion",
            "--scope",
            "personal",
            "--held-on",
            "2026-09-09",
        ],
    )

    events = [
        json.loads(line)
        for line in next(audit_root.glob("*.jsonl"))
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    audit_text = json.dumps(events)
    assert result.exit_code == 0
    assert [event["event_type"] for event in events] == [
        "meeting-note.prepared",
        "meeting-note.committed",
    ]
    assert all(event["profile"] == "personal" for event in events)
    assert "Private planning discussion" not in audit_text


def test_meeting_start_distinguishes_capture_date_from_meeting_date(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    monkeypatch.setattr("edifice.meeting_note._today", lambda: date(2026, 9, 9))

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "meeting",
            "start",
            "--title",
            "Yesterday review",
            "--scope",
            "personal",
            "--held-on",
            "2026-09-08",
        ],
    )

    note = (
        vault_root / "10-personal/notes/meetings/2026-09-08-yesterday-review.md"
    ).read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert "created: 2026-09-09" in note
    assert "meeting_on: 2026-09-08" in note


def test_meeting_start_requires_work_classification(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "meeting",
            "start",
            "--title",
            "Architecture sync",
            "--scope",
            "work",
            "--held-on",
            "2026-09-09",
        ],
    )

    assert result.exit_code != 0
    assert "Work meeting notes require --classification." in result.output
    assert not (vault_root / "20-work" / "notes" / "meetings").exists()


def test_meeting_start_refuses_to_overwrite_existing_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    arguments = [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(tmp_path / "audit"),
        "--dry-run",
        "meeting",
        "start",
        "--title",
        "Architecture sync",
        "--scope",
        "work",
        "--classification",
        "netflix-internal",
        "--held-on",
        "2026-09-09",
    ]
    runner = CliRunner()
    first = runner.invoke(cli, arguments)
    note_path = vault_root / "20-work/notes/meetings/2026-09-09-architecture-sync.md"
    original = note_path.read_bytes()

    second = runner.invoke(cli, arguments)

    assert first.exit_code == 0
    assert second.exit_code != 0
    assert (
        "Meeting note already exists: 2026-09-09-architecture-sync.md" in second.output
    )
    assert note_path.read_bytes() == original


def test_meeting_series_create_builds_reusable_human_owned_series(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    series_note = Path("20-work/notes/meetings/series/1-1-with-jordan.md")
    manifest_path = (
        vault_root / "20-work/operations/meeting-series/1-1-with-jordan.json"
    )

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "meeting",
            "series",
            "create",
            "--title",
            "1:1 with Jordan",
            "--scope",
            "work",
            "--classification",
            "netflix-internal",
        ],
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    note = (vault_root / series_note).read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert result.output == (
        "Created meeting series: 1-1-with-jordan.\n"
        f"Would open {series_note} in Obsidian.\n"
    )
    assert manifest["slug"] == "1-1-with-jordan"
    assert manifest["title"] == "1:1 with Jordan"
    assert manifest["scope"] == "work"
    assert manifest["classification"] == "netflix-internal"
    assert manifest["meetings"] == []
    assert "type: meeting-series" in note
    assert "ownership: human" in note
    assert "# 1:1 with Jordan" in note
    assert "## Purpose" in note
    assert "## Standing topics" in note
    assert "## Meeting history" in note
    audit_text = next((tmp_path / "audit").glob("*.jsonl")).read_text(encoding="utf-8")
    assert "1:1 with Jordan" not in audit_text


def test_meeting_series_start_links_occurrences_and_refreshes_history(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    created = runner.invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "--dry-run",
            "meeting",
            "series",
            "create",
            "--title",
            "1:1 with Jordan",
            "--scope",
            "work",
            "--classification",
            "netflix-internal",
        ],
    )
    assert created.exit_code == 0
    series_note_path = vault_root / "20-work/notes/meetings/series/1-1-with-jordan.md"
    series_note_path.write_text(
        series_note_path.read_text(encoding="utf-8").replace(
            "## Standing topics\n",
            "## Standing topics\n\n- Career discussion\n",
        ),
        encoding="utf-8",
    )

    first = runner.invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "--dry-run",
            "meeting",
            "series",
            "start",
            "1-1-with-jordan",
            "--held-on",
            "2026-09-09",
        ],
    )
    second = runner.invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "--dry-run",
            "meeting",
            "series",
            "start",
            "1-1-with-jordan",
            "--held-on",
            "2026-09-16",
        ],
    )

    first_path = Path("20-work/notes/meetings/2026-09-09-1-1-with-jordan.md")
    second_path = Path("20-work/notes/meetings/2026-09-16-1-1-with-jordan.md")
    first_note = (vault_root / first_path).read_text(encoding="utf-8")
    second_note = (vault_root / second_path).read_text(encoding="utf-8")
    series_note = series_note_path.read_text(encoding="utf-8")
    manifest = json.loads(
        (
            vault_root / "20-work/operations/meeting-series/1-1-with-jordan.json"
        ).read_text(encoding="utf-8")
    )

    assert first.exit_code == 0
    assert first.output == (
        f"Created meeting note: {first_path}.\nWould open {first_path} in Obsidian.\n"
    )
    assert second.exit_code == 0
    assert "type: meeting-note" in first_note
    assert "series_slug: 1-1-with-jordan" in first_note
    assert "previous_meeting: not-applicable" in first_note
    assert "## Preparation" in first_note
    assert "### Carry-forward" in first_note
    assert "No previous meeting in this series." in first_note
    assert "### Topics to discuss" in first_note
    assert "### Questions to ask" in first_note
    assert "### Decisions needed" in first_note
    assert "### Pre-reading" in first_note
    assert (
        'previous_meeting: "[[20-work/notes/meetings/2026-09-09-1-1-with-jordan]]"'
    ) in second_note
    assert (
        "Previous meeting: [[20-work/notes/meetings/"
        "2026-09-09-1-1-with-jordan|2026-09-09]]"
    ) in second_note
    assert "2026-09-09-1-1-with-jordan" in series_note
    assert "2026-09-16-1-1-with-jordan" in series_note
    assert "- Career discussion" in series_note
    assert [meeting["meeting_on"] for meeting in manifest["meetings"]] == [
        "2026-09-09",
        "2026-09-16",
    ]


def test_meeting_series_start_rejects_duplicate_date_without_changing_series(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    create_arguments = [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
        "--dry-run",
        "meeting",
        "series",
        "create",
        "--title",
        "1:1 with Jordan",
        "--scope",
        "work",
        "--classification",
        "netflix-internal",
    ]
    start_arguments = [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
        "--dry-run",
        "meeting",
        "series",
        "start",
        "1-1-with-jordan",
        "--held-on",
        "2026-09-09",
    ]
    assert runner.invoke(cli, create_arguments).exit_code == 0
    assert runner.invoke(cli, start_arguments).exit_code == 0
    manifest_path = (
        vault_root / "20-work/operations/meeting-series/1-1-with-jordan.json"
    )
    series_note_path = vault_root / "20-work/notes/meetings/series/1-1-with-jordan.md"
    manifest_before = manifest_path.read_bytes()
    series_note_before = series_note_path.read_bytes()

    duplicate = runner.invoke(cli, start_arguments)

    assert duplicate.exit_code != 0
    assert (
        "Meeting already exists for series 1-1-with-jordan: 2026-09-09"
        in duplicate.output
    )
    assert manifest_path.read_bytes() == manifest_before
    assert series_note_path.read_bytes() == series_note_before
