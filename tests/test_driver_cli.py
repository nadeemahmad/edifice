import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from edifice.cli import cli


def _open_in_obsidian(command: list[str], *, check: bool) -> None:
    assert check
    assert command[0] == "open"
    assert command[1].startswith("obsidian://open?")


def test_launcher_runs_current_source(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    vault_root = tmp_path / "edifice"
    (vault_root / "home.md").parent.mkdir(parents=True)
    (vault_root / "home.md").write_text("# Edifice\n", encoding="utf-8")
    environment = {
        key: value for key, value in os.environ.items() if key != "PYTHONPATH"
    } | {
        "EDIFICE_VAULT": str(vault_root),
        "EDIFICE_AUDIT_ROOT": str(tmp_path / "audit"),
    }

    result = subprocess.run(
        [str(project_root / "bin" / "edifice"), "--dry-run", "start"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert result.stdout == "Would open home.md in Obsidian.\n"


def test_start_dry_run_points_to_home(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    (vault_root / "home.md").parent.mkdir(parents=True)
    (vault_root / "home.md").write_text("# Edifice\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "start",
        ],
    )

    assert result.exit_code == 0
    assert result.output == "Would open home.md in Obsidian.\n"


def test_work_dry_run_uses_current_project_pointer(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    project_path = Path("10-personal/operations/projects/first-deliverable.md")
    target = vault_root / project_path
    target.parent.mkdir(parents=True)
    target.write_text("# First Deliverable\n", encoding="utf-8")
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps({"work": project_path.as_posix()}),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "work",
        ],
    )

    assert result.exit_code == 0
    assert result.output == f"Would open {project_path} in Obsidian.\n"


def test_work_context_dry_run_opens_work_home(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    work_home = Path("20-work/home.md")
    target = vault_root / work_home
    target.parent.mkdir(parents=True)
    target.write_text("# Work\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "work-context",
        ],
    )

    assert result.exit_code == 0
    assert result.output == f"Would open {work_home} in Obsidian.\n"


def test_today_dry_run_opens_selected_daily_review(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    daily_path = Path("10-personal/operations/reviews/daily/2026-09-07.md")
    target = vault_root / daily_path
    target.parent.mkdir(parents=True)
    target.write_text("# Daily Review\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "today",
            "--date",
            "2026-09-07",
        ],
    )

    assert result.exit_code == 0
    assert result.output == f"Would open {daily_path} in Obsidian.\n"


def test_today_links_work_plan_without_copying_work_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "edifice"
    personal = vault_root / "10-personal/operations/reviews/daily/2026-10-05.md"
    personal.parent.mkdir(parents=True)
    original = "# Daily Review\n\n## Intended result\n\nGo for a walk.\n"
    personal.write_text(original, encoding="utf-8")
    work = vault_root / "20-work/operations/reviews/daily/2026-10-05.md"
    work.parent.mkdir(parents=True)
    work_content = "# Work plan\n\n- [ ] Internal evaluation task\n"
    work.write_text(work_content, encoding="utf-8")
    monkeypatch.setattr("edifice.cli.subprocess.run", _open_in_obsidian)
    arguments = [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(tmp_path / "audit"),
        "today",
        "--date",
        "2026-10-05",
    ]

    result = CliRunner().invoke(cli, arguments)

    assert result.exit_code == 0, result.output
    updated = personal.read_text(encoding="utf-8")
    assert updated.startswith(original)
    assert (
        "[[20-work/operations/reviews/daily/2026-10-05|Today's work plan]]" in updated
    )
    assert "Internal evaluation task" not in updated
    assert work.read_text(encoding="utf-8") == work_content

    repeated = CliRunner().invoke(cli, arguments)

    assert repeated.exit_code == 0, repeated.output
    assert personal.read_text(encoding="utf-8") == updated


def test_today_creates_missing_daily_review_and_records_redacted_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "edifice"
    work = vault_root / "20-work/operations/reviews/daily/2026-10-05.md"
    work.parent.mkdir(parents=True)
    work.write_text("Confidential task wording\n", encoding="utf-8")
    audit_root = tmp_path / "audit"
    monkeypatch.setattr("edifice.cli.subprocess.run", _open_in_obsidian)

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "today",
            "--date",
            "2026-10-05",
        ],
    )

    assert result.exit_code == 0, result.output
    daily = vault_root / "10-personal/operations/reviews/daily/2026-10-05.md"
    content = daily.read_text(encoding="utf-8")
    assert "scheduled_for: 2026-10-05" in content
    assert "## Intended result" in content
    assert (
        "[[20-work/operations/reviews/daily/2026-10-05|Today's work plan]]" in content
    )
    events = [
        json.loads(line)
        for audit_file in audit_root.glob("*.jsonl")
        for line in audit_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event_type"] for event in events] == [
        "daily-review.prepared",
        "daily-review.committed",
    ]
    assert all(event["target"].endswith("/daily/2026-10-05.md") for event in events)
    assert "Confidential task wording" not in content + json.dumps(events)


def test_today_dry_run_previews_missing_review_without_writing(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    work = vault_root / "20-work/operations/reviews/daily/2026-10-05.md"
    work.parent.mkdir(parents=True)
    work.write_text("# Work plan\n", encoding="utf-8")
    audit_root = tmp_path / "audit"

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "--dry-run",
            "today",
            "--date",
            "2026-10-05",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (
        "Would create 10-personal/operations/reviews/daily/2026-10-05.md."
        in result.output
    )
    assert "Would link 20-work/operations/reviews/daily/2026-10-05.md" in result.output
    assert not (vault_root / "10-personal").exists()
    assert not audit_root.exists()


def test_today_does_not_create_work_plan_when_none_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "edifice"
    monkeypatch.setattr("edifice.cli.subprocess.run", _open_in_obsidian)

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "today",
            "--date",
            "2026-10-05",
        ],
    )

    assert result.exit_code == 0, result.output
    daily = vault_root / "10-personal/operations/reviews/daily/2026-10-05.md"
    assert "## Work plan" not in daily.read_text(encoding="utf-8")
    assert not (vault_root / "20-work").exists()


def test_today_rejects_symlink_to_human_owned_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    human_note = vault_root / "10-personal/notes/private.md"
    human_note.parent.mkdir(parents=True)
    human_note.write_text("Owner writing\n", encoding="utf-8")
    daily = vault_root / "10-personal/operations/reviews/daily/2026-10-05.md"
    daily.parent.mkdir(parents=True)
    daily.symlink_to(human_note)

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "today",
            "--date",
            "2026-10-05",
        ],
    )

    assert result.exit_code != 0
    assert "Daily review path" in result.output
    assert human_note.read_text(encoding="utf-8") == "Owner writing\n"


def test_review_dry_run_opens_week_containing_selected_date(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    weekly_path = Path("10-personal/operations/reviews/weekly/2026-09-07-weekly.md")
    target = vault_root / weekly_path
    target.parent.mkdir(parents=True)
    target.write_text("# Weekly Review\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "--dry-run",
            "review",
            "--date",
            "2026-09-10",
        ],
    )

    assert result.exit_code == 0
    assert result.output == f"Would open {weekly_path} in Obsidian.\n"


def test_status_summarizes_current_operating_state(tmp_path: Path) -> None:
    vault_root = tmp_path / "edifice"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] First capture.\n- [x] Routed capture.\n- [ ] Second capture.\n",
        encoding="utf-8",
    )
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps(
            {
                "work": "10-personal/operations/projects/first-deliverable.md",
                "question": (
                    "10-personal/operations/questions/select-first-deliverable.md"
                ),
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "status",
            "--date",
            "2026-09-07",
        ],
    )

    assert result.exit_code == 0
    assert result.output == (
        f"Vault: {vault_root}\n"
        "Inbox: 2 unprocessed\n"
        "Work: 10-personal/operations/projects/first-deliverable.md\n"
        "Question: 10-personal/operations/questions/select-first-deliverable.md\n"
        "Today: 10-personal/operations/reviews/daily/2026-09-07.md\n"
        "Review: "
        "10-personal/operations/reviews/weekly/2026-09-07-weekly.md\n"
        "Git: unavailable\n"
    )
