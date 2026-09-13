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


def test_project_start_creates_selects_and_lists_stable_project(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    current_path = _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_project._today", lambda: date(2026, 9, 13))
    runner = CliRunner()
    base = _base_arguments(vault_root, audit_root)

    started = runner.invoke(
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
    )
    listed = runner.invoke(cli, [*base, "project", "list"])

    registry_path = vault_root / "20-work" / "operations" / "projects" / "index.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    project = next(iter(registry["projects"].values()))
    note_path = vault_root / project["note_path"]
    current = json.loads(current_path.read_text(encoding="utf-8"))

    assert started.exit_code == 0
    assert started.output.startswith("Created project: document-intelligence (project-")
    assert "Selected: 20-work/operations/projects/document-intelligence.md." in (
        started.output
    )
    assert project["slug"] == "document-intelligence"
    assert project["status"] == "active"
    assert project["classification"] == "netflix-internal"
    assert current["work"] == project["note_path"]
    note = note_path.read_text(encoding="utf-8")
    assert f"id: {project['project_id']}" in note
    assert "primary_anchor: local-project" in note
    assert listed.exit_code == 0
    assert listed.output == (
        f"* document-intelligence | active | {project['project_id']} | "
        "Document intelligence\n"
    )


def test_project_select_and_status_use_registered_identity(
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

    selected = runner.invoke(
        cli,
        [*base, "project", "select", "document-intelligence"],
    )
    status = runner.invoke(
        cli,
        [*base, "project", "status", "document-intelligence"],
    )
    marked = runner.invoke(
        cli,
        [*base, "project", "mark", "model-gateway", "--status", "on-hold"],
    )

    assert selected.exit_code == 0
    assert selected.output == (
        "Selected project: document-intelligence.\n"
        "Note: 20-work/operations/projects/document-intelligence.md.\n"
    )
    assert status.exit_code == 0
    assert "Project: Document intelligence\n" in status.output
    assert "Status: active\n" in status.output
    assert "Selected: yes\n" in status.output
    assert marked.exit_code == 0
    assert marked.output == "Marked project model-gateway as on-hold.\n"


def test_project_start_supports_personal_scope_with_separate_registry(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    current_path = _create_current_pointer(vault_root)
    monkeypatch.setattr("edifice.work_project._today", lambda: date(2026, 9, 13))

    started = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "project",
            "start",
            "--name",
            "Home library",
            "--scope",
            "personal",
            "--review-on",
            "2026-10-01",
        ],
    )

    registry_path = (
        vault_root / "10-personal" / "operations" / "projects" / "index.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    project = next(iter(registry["projects"].values()))
    current = json.loads(current_path.read_text(encoding="utf-8"))

    assert started.exit_code == 0
    assert project["scope"] == "personal"
    assert project["classification"] == "personal"
    assert project["note_path"] == ("10-personal/operations/projects/home-library.md")
    assert current["personal_project"] == project["note_path"]
    assert current["work"] == project["note_path"]
