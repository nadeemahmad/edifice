import json
from datetime import date
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from edifice.cli import cli


def _base_arguments(vault_root: Path, audit_root: Path) -> list[str]:
    return [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
    ]


def _create_current_pointer(vault_root: Path) -> Path:
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps(
            {
                "question": (
                    "10-personal/operations/questions/select-first-deliverable.md"
                ),
                "work": "10-personal/operations/projects/first-deliverable.md",
            }
        ),
        encoding="utf-8",
    )
    return current_path


def test_task_start_creates_context_free_work_task_and_selects_it(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    current_path = _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_task._today", lambda: date(2026, 9, 8))

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "task",
            "start",
            "--name",
            "Investigate evaluation failures",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )

    relative_path = Path(
        "20-work/operations/projects/investigate-evaluation-failures.md"
    )
    note = (vault_root / relative_path).read_text(encoding="utf-8")
    current = json.loads(current_path.read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert result.output == (
        "Created work task: investigate-evaluation-failures.\n"
        f"Note: {relative_path}.\n"
        "Run `edifice work` to open it.\n"
    )
    assert "type: project" in note
    assert "status: active" in note
    assert 'classification: "netflix-internal"' in note
    assert "review_on: 2026-09-15" in note
    assert "authoritative_source: not-applicable" in note
    assert "jira: not-applicable" in note
    assert "repository: not-applicable" in note
    assert "# Investigate evaluation failures" in note
    assert "## Manual context" in note
    assert "### Notes" in note
    assert "### Links" in note
    assert "### PDFs" in note
    assert current["work"] == relative_path.as_posix()
    assert current["question"] == (
        "10-personal/operations/questions/select-first-deliverable.md"
    )


def test_task_start_makes_work_command_open_new_task(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_task._today", lambda: date(2026, 9, 8))
    runner = CliRunner()
    started = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "task",
            "start",
            "--name",
            "Investigate evaluation failures",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )
    assert started.exit_code == 0

    opened = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "--dry-run",
            "work",
        ],
    )

    relative_path = Path(
        "20-work/operations/projects/investigate-evaluation-failures.md"
    )
    assert opened.exit_code == 0
    assert opened.output == f"Would open {relative_path} in Obsidian.\n"


def test_task_start_rejects_existing_note_without_changing_current_pointer(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    current_path = _create_current_pointer(vault_root)
    existing_path = (
        vault_root / "20-work" / "operations" / "projects" / "existing-task.md"
    )
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("Owner content.\n", encoding="utf-8")
    before_current = current_path.read_bytes()
    monkeypatch.setattr("edifice.work_task._today", lambda: date(2026, 9, 8))

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "task",
            "start",
            "--name",
            "Existing task",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )

    assert result.exit_code != 0
    assert "Work task already exists: existing-task" in result.output
    assert existing_path.read_text(encoding="utf-8") == "Owner content.\n"
    assert current_path.read_bytes() == before_current


def test_task_start_rejects_past_review_date(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_task._today", lambda: date(2026, 9, 8))

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "task",
            "start",
            "--name",
            "Past review",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-07",
        ],
    )

    assert result.exit_code != 0
    assert "Review date must be today or later: 2026-09-07" in result.output
    assert not (
        vault_root / "20-work" / "operations" / "projects" / "past-review.md"
    ).exists()


def test_task_start_rejects_name_without_filename_characters(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_task._today", lambda: date(2026, 9, 8))

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "task",
            "start",
            "--name",
            "---",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )

    assert result.exit_code != 0
    assert "Task name must contain letters or numbers." in result.output


def test_task_start_removes_new_note_when_current_pointer_update_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    current_path = _create_current_pointer(vault_root)
    before_current = current_path.read_bytes()
    monkeypatch.setattr("edifice.work_task._today", lambda: date(2026, 9, 8))

    def fail_pointer_update(_target: Path, _content: bytes) -> None:
        raise PermissionError("pointer is read-only")

    monkeypatch.setattr(
        "edifice.work_task._replace_atomically",
        fail_pointer_update,
    )

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "task",
            "start",
            "--name",
            "Rollback task",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )

    assert result.exit_code != 0
    assert not (
        vault_root / "20-work" / "operations" / "projects" / "rollback-task.md"
    ).exists()
    assert current_path.read_bytes() == before_current
