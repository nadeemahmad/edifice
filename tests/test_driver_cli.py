import json
import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from edifice.cli import cli


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
