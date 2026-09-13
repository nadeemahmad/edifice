import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import cast

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
    from edifice import work_project

    replace_atomically = cast(
        Callable[[Path, bytes], None],
        work_project.__dict__["_replace"],
    )

    def fail_pointer_update(target: Path, content: bytes) -> None:
        if target == current_path:
            raise PermissionError("pointer is read-only")
        replace_atomically(target, content)

    monkeypatch.setattr(
        "edifice.work_project._replace",
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


def test_task_add_list_and_complete_preserve_project_relationship(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_project._today", lambda: date(2026, 9, 13))
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
            "task",
            "add",
            "Review architecture memo",
            "--project",
            "document-intelligence",
        ],
        catch_exceptions=False,
    )
    assert added.exit_code == 0, added.output
    task_id = added.output.split("Created task: ", 1)[1].split(".", 1)[0]
    listed = runner.invoke(
        cli,
        [*base, "task", "list", "--project", "document-intelligence"],
    )
    completed = runner.invoke(
        cli,
        [*base, "task", "complete", task_id],
    )

    task_index = json.loads(
        (vault_root / "20-work" / "operations" / "tasks" / "index.json").read_text(
            encoding="utf-8"
        )
    )
    project_index = json.loads(
        (vault_root / "20-work" / "operations" / "projects" / "index.json").read_text(
            encoding="utf-8"
        )
    )
    project = next(iter(project_index["projects"].values()))
    task = task_index["tasks"][task_id]
    note = (vault_root / project["note_path"]).read_text(encoding="utf-8")

    assert task_id.startswith("task-")
    assert listed.output == (
        f"{task_id} | open | document-intelligence | Review architecture memo\n"
    )
    assert completed.exit_code == 0
    assert completed.output == f"Completed task: {task_id}.\n"
    assert task["project_id"] == project["project_id"]
    assert task["status"] == "completed"
    assert f"- [x] Review architecture memo ^{task_id}" in note


def test_task_creation_supports_current_project_and_explicit_unassigned_scope(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_project._today", lambda: date(2026, 9, 13))
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

    automatic = runner.invoke(
        cli,
        [*base, "task", "add", "Review architecture memo"],
    )
    unassigned = runner.invoke(
        cli,
        [
            *base,
            "task",
            "add",
            "Organize books",
            "--scope",
            "personal",
            "--no-project",
        ],
    )

    work_index = json.loads(
        (vault_root / "20-work/operations/tasks/index.json").read_text()
    )
    personal_index = json.loads(
        (vault_root / "10-personal/operations/tasks/index.json").read_text()
    )
    work_task = next(iter(work_index["tasks"].values()))
    personal_task = next(iter(personal_index["tasks"].values()))

    assert automatic.exit_code == 0
    assert "Assignment: current project document-intelligence." in automatic.output
    assert work_task["project_id"] is not None
    assert work_task["assignment_history"][0]["reason"] == "current-project"
    assert unassigned.exit_code == 0
    assert "Assignment: none (personal)." in unassigned.output
    assert personal_task["project_id"] is None
    assert (vault_root / "10-personal/operations/tasks/inbox.md").read_text().count(
        "Organize books"
    ) == 1


def test_task_assign_reassign_and_unassign_preserve_identity_and_history(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_project._today", lambda: date(2026, 9, 13))
    runner = CliRunner()
    base = _base_arguments(vault_root, audit_root)
    for name in ("Document intelligence", "Model gateway"):
        assert (
            runner.invoke(
                cli,
                [
                    *base,
                    "project",
                    "start",
                    "--name",
                    name,
                    "--classification",
                    "netflix-internal",
                    "--review-on",
                    "2026-10-01",
                ],
            ).exit_code
            == 0
        )
    created = runner.invoke(
        cli,
        [
            *base,
            "task",
            "add",
            "Review architecture memo",
            "--scope",
            "work",
            "--no-project",
        ],
    )
    task_id = created.output.split("Created task: ", 1)[1].split(".", 1)[0]

    assigned = runner.invoke(
        cli,
        [*base, "task", "assign", task_id, "--project", "document-intelligence"],
    )
    reassigned = runner.invoke(
        cli,
        [*base, "task", "reassign", task_id, "--project", "model-gateway"],
    )
    unassigned = runner.invoke(cli, [*base, "task", "unassign", task_id])

    index = json.loads((vault_root / "20-work/operations/tasks/index.json").read_text())
    task = index["tasks"][task_id]
    project_index = json.loads(
        (vault_root / "20-work/operations/projects/index.json").read_text()
    )
    notes = {
        project["slug"]: (vault_root / project["note_path"]).read_text()
        for project in project_index["projects"].values()
    }

    assert assigned.exit_code == 0
    assert reassigned.exit_code == 0
    assert unassigned.exit_code == 0
    assert task["project_id"] is None
    assert len(task["assignment_history"]) == 3
    assert [entry["reason"] for entry in task["assignment_history"]] == [
        "explicit",
        "reassigned",
        "unassigned",
    ]
    assert task_id not in notes["document-intelligence"]
    assert task_id not in notes["model-gateway"]
    assert task_id in (vault_root / "20-work/operations/tasks/inbox.md").read_text()


def test_task_auto_assign_previews_and_applies_unique_title_match(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_project._today", lambda: date(2026, 9, 13))
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
    created = runner.invoke(
        cli,
        [
            *base,
            "task",
            "add",
            "Draft document intelligence design",
            "--scope",
            "work",
            "--no-project",
        ],
    )
    task_id = created.output.split("Created task: ", 1)[1].split(".", 1)[0]

    preview = runner.invoke(cli, [*base, "task", "auto-assign", task_id])
    applied = runner.invoke(
        cli,
        [*base, "task", "auto-assign", task_id, "--apply"],
    )

    assert preview.exit_code == 0
    assert preview.output == (
        f"{task_id} -> document-intelligence "
        "(matching terms: document, intelligence). Preview only.\n"
    )
    assert applied.exit_code == 0
    assert applied.output == (
        f"{task_id} -> document-intelligence "
        "(matching terms: document, intelligence). Assigned.\n"
    )
