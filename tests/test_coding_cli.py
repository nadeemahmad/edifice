import hashlib
import json
import os
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

from edifice.agent_assignment import validate_agent_assignment
from edifice.cli import cli


def _base_arguments(vault_root: Path, audit_root: Path) -> list[str]:
    return [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
    ]


def _run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _create_repository(
    repository: Path,
    *,
    owned_paths: list[str] | None = None,
    source_symlink: str | None = None,
    include_registry: bool = True,
) -> dict[str, object]:
    files = {
        "AGENTS.md": "# Repository instructions\n",
        "docs/agent-context.md": "# Agent context\n",
        "docs/engineering/owner-practices.md": "# Owner practices\n",
        "docs/workstreams/example.md": "# Example workstream\n",
    }
    if source_symlink is None:
        files["src/AGENTS.md"] = "# Source instructions\n"
        files["src/example.py"] = 'MESSAGE = "unchanged"\n'
    for relative_path, content in files.items():
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if source_symlink is not None:
        (repository / "src").symlink_to(source_symlink, target_is_directory=True)

    registry: dict[str, object] = {
        "schema_version": 1,
        "integration_owned_paths": [],
        "workstreams": [
            {
                "id": "example",
                "title": "Example",
                "status": "active",
                "mode": "design",
                "context": "docs/workstreams/example.md",
                "owned_paths": (
                    ["src/example.py"] if owned_paths is None else owned_paths
                ),
                "shared_paths": [],
                "dependencies": [],
            }
        ],
    }
    registry_path = repository / "docs" / "workstreams" / "registry.json"
    if include_registry:
        registry_path.write_text(json.dumps(registry), encoding="utf-8")

    _run_git(repository, "init", "-b", "nahmad/example-codex")
    _run_git(repository, "config", "user.email", "test@example.com")
    _run_git(repository, "config", "user.name", "Test User")
    _run_git(repository, "add", ".")
    _run_git(repository, "commit", "-m", "Initial repository")
    return registry


def test_code_start_creates_governed_run_and_assignment_without_touching_repository(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    registry = _create_repository(repository)
    revision = _run_git(repository, "rev-parse", "HEAD")
    before_status = _run_git(repository, "status", "--porcelain")
    created_at = datetime(2026, 9, 13, 16, 30, tzinfo=UTC)
    monkeypatch.setattr("edifice.coding_run._now", lambda: created_at)

    vault_root = tmp_path / "vault"
    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "First coding run",
            "--objective",
            "Change one observable behavior.",
            "--jira",
            "EDIFICE-123",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "understand",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    run_directory = (
        vault_root / "20-work" / "operations" / "coding-runs" / "first-coding-run"
    )
    run_path = run_directory / "coding-run.json"
    assignment_path = run_directory / "agent-assignment.preview.json"
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
    context_hashes = {
        entry["path"]: entry["sha256"] for entry in coding_run["context_manifest"]
    }

    assert result.exit_code == 0
    assert result.output == (
        "Created coding run: first-coding-run.\n"
        "Run: 20-work/operations/coding-runs/first-coding-run/coding-run.json.\n"
        "Assignment preview: "
        "20-work/operations/coding-runs/first-coding-run/"
        "agent-assignment.preview.json.\n"
        "No agent launched and no external system contacted.\n"
    )
    assert coding_run["schema_version"] == 1
    assert coding_run["status"] == "active"
    assert coding_run["created_at"] == "2026-09-13T16:30:00+00:00"
    assert coding_run["objective"] == "Change one observable behavior."
    assert coding_run["persistence_reason"] == (
        "Active coding-run state required for the current objective."
    )
    assert coding_run["jira"] == {
        "key": "EDIFICE-123",
        "title": None,
        "url": None,
        "evidence_status": "pending-verification",
    }
    assert coding_run["repository"] == {
        "path": str(repository),
        "branch": "nahmad/example-codex",
        "revision": revision,
        "working_tree": "clean",
    }
    assert coding_run["active_mode"] == "design"
    assert coding_run["learning_level"] == "understand"
    assert coding_run["writable_paths"] == []
    assert coding_run["assignment"]["status"] == "not-launched"
    assert coding_run["gates"]["design"] == "required"
    assert coding_run["gates"]["tdd"] == "pending"
    assert coding_run["gates"]["verification"] == "pending"
    assert coding_run["gates"]["review"] == "pending"
    assert coding_run["gates"]["pr_draft"] == "pending"
    assert coding_run["evidence"] == {
        "design_records": [],
        "tdd_cycles": [],
        "verification_runs": [],
        "review_runs": [],
        "closeouts": [],
        "pr_drafts": [],
    }
    assert context_hashes == {
        path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
        for path in (
            "AGENTS.md",
            "docs/agent-context.md",
            "docs/engineering/owner-practices.md",
            "docs/workstreams/example.md",
            "src/AGENTS.md",
        )
    }
    assert assignment["base_revision"] == revision
    assert assignment["mode"] == "design"
    assert assignment["learning_level"] == "understand"
    assert assignment["writable_paths"] == []
    validate_agent_assignment(
        assignment=assignment,
        registry=registry,
        repository_root=repository,
        expected_branch="nahmad/example-codex",
        expected_revision=revision,
    )
    assert _run_git(repository, "status", "--porcelain") == before_status


def test_code_start_retry_returns_identical_existing_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    created_at = datetime(2026, 9, 13, 16, 30, tzinfo=UTC)
    monkeypatch.setattr("edifice.coding_run._now", lambda: created_at)
    vault_root = tmp_path / "vault"
    arguments = [
        *_base_arguments(vault_root, tmp_path / "audit"),
        "code",
        "start",
        "--name",
        "Retryable run",
        "--objective",
        "Preserve one durable run.",
        "--jira",
        "EDIFICE-124",
        "--repo",
        str(repository),
        "--workstream",
        "example",
        "--mode",
        "design",
        "--learning-level",
        "brief",
        "--classification",
        "netflix-internal",
        "--review-on",
        "2026-09-20",
    ]
    runner = CliRunner()
    first = runner.invoke(cli, arguments)
    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "retryable-run"
        / "coding-run.json"
    )
    assignment_path = run_path.with_name("agent-assignment.preview.json")
    before_run = run_path.read_bytes()
    before_assignment = assignment_path.read_bytes()

    retry = runner.invoke(cli, arguments)

    assert first.exit_code == 0
    assert retry.exit_code == 0
    assert retry.output.startswith("Existing coding run: retryable-run.\n")
    assert run_path.read_bytes() == before_run
    assert assignment_path.read_bytes() == before_assignment


@pytest.mark.parametrize("mode", ["experiment", "implementation"])
def test_code_start_write_modes_receive_registered_write_scope(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    mode: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    monkeypatch.setattr(
        "edifice.coding_run._now",
        lambda: datetime(2026, 9, 13, 16, 30, tzinfo=UTC),
    )
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            f"{mode} scope",
            "--objective",
            "Permit only registered implementation writes.",
            "--jira",
            "EDIFICE-130",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            mode,
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / f"{mode}-scope"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment = json.loads(
        run_path.with_name("agent-assignment.preview.json").read_text(encoding="utf-8")
    )

    assert result.exit_code == 0
    assert coding_run["writable_paths"] == ["src/example.py"]
    assert assignment["writable_paths"] == ["src/example.py"]
    assert (
        "Do not modify the target repository." not in assignment["prohibited_effects"]
    )
    assert (
        "Do not modify paths outside the declared writable paths."
        in assignment["prohibited_effects"]
    )


@pytest.mark.parametrize("mode", ["research", "design", "verification", "review"])
def test_code_start_read_only_modes_receive_no_write_scope(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    mode: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    monkeypatch.setattr(
        "edifice.coding_run._now",
        lambda: datetime(2026, 9, 13, 16, 30, tzinfo=UTC),
    )
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            f"{mode} scope",
            "--objective",
            "Preserve read-only mode permissions.",
            "--jira",
            "EDIFICE-131",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            mode,
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    assignment_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / f"{mode}-scope"
        / "agent-assignment.preview.json"
    )
    assignment = json.loads(assignment_path.read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert assignment["writable_paths"] == []
    assert "Do not modify the target repository." in assignment["prohibited_effects"]


def test_code_start_rejects_conflicting_retry_without_changing_existing_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    monkeypatch.setattr(
        "edifice.coding_run._now",
        lambda: datetime(2026, 9, 13, 16, 30, tzinfo=UTC),
    )
    vault_root = tmp_path / "vault"
    common_arguments = [
        *_base_arguments(vault_root, tmp_path / "audit"),
        "code",
        "start",
        "--name",
        "Stable run",
        "--jira",
        "EDIFICE-125",
        "--repo",
        str(repository),
        "--workstream",
        "example",
        "--mode",
        "design",
        "--learning-level",
        "brief",
        "--classification",
        "netflix-internal",
        "--review-on",
        "2026-09-20",
    ]
    runner = CliRunner()
    first = runner.invoke(
        cli,
        [*common_arguments, "--objective", "Original objective."],
    )
    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "stable-run"
        / "coding-run.json"
    )
    before = run_path.read_bytes()

    conflict = runner.invoke(
        cli,
        [*common_arguments, "--objective", "Different objective."],
    )

    assert first.exit_code == 0
    assert conflict.exit_code != 0
    assert (
        "Coding run name identifies a run with different inputs: stable-run"
        in conflict.output
    )
    assert run_path.read_bytes() == before


def test_code_start_removes_partial_run_when_assignment_write_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    monkeypatch.setattr(
        "edifice.coding_run._now",
        lambda: datetime(2026, 9, 13, 16, 30, tzinfo=UTC),
    )
    write_count = 0

    def fail_second_write(path: Path, value: dict[str, object]) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("assignment disk failure")
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("edifice.coding_run._write_json", fail_second_write)
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Interrupted run",
            "--objective",
            "Do not preserve partial state.",
            "--jira",
            "EDIFICE-126",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    run_root = vault_root / "20-work" / "operations" / "coding-runs"
    assert result.exit_code != 0
    assert "Cannot create coding run: assignment disk failure" in result.output
    assert list(run_root.iterdir()) == []


def test_code_start_rejects_unsafe_registered_path_before_context_discovery(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository, owned_paths=["/outside/repository.py"])
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Unsafe scope",
            "--objective",
            "Reject an unsafe registered path.",
            "--jira",
            "EDIFICE-127",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    assert result.exit_code != 0
    assert "Unsafe registered writable path: /outside/repository.py" in result.output
    assert not vault_root.exists()


def test_code_start_rejects_writable_path_resolving_outside_repository(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text(
        "# Instructions outside the repository\n",
        encoding="utf-8",
    )
    (outside / "example.py").write_text(
        'MESSAGE = "outside"\n',
        encoding="utf-8",
    )
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository, source_symlink="../outside")
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Symlink escape",
            "--objective",
            "Reject paths outside the repository.",
            "--jira",
            "EDIFICE-128",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    assert result.exit_code != 0
    assert "Registered writable path resolves outside repository" in result.output
    assert not vault_root.exists()


def test_code_start_rejects_repository_change_during_context_preparation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)

    def mutate_after_clean_check(
        registry: dict[str, object],
        workstream_id: str,
    ) -> dict[str, object]:
        workstreams = cast(list[object], registry["workstreams"])
        workstream = cast(dict[str, object], workstreams[0])
        assert workstream["id"] == workstream_id
        (repository / "AGENTS.md").write_text(
            "# Changed after the clean check\n",
            encoding="utf-8",
        )
        return workstream

    vault_root = tmp_path / "vault"
    monkeypatch.setattr(
        "edifice.coding_run._find_workstream",
        mutate_after_clean_check,
    )
    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Racing context",
            "--objective",
            "Reject context that differs from the recorded revision.",
            "--jira",
            "EDIFICE-129",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    assert result.exit_code != 0
    assert "Repository changed while preparing coding run." in result.output
    assert not vault_root.exists()


def test_code_start_rechecks_repository_after_acquiring_run_lock(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)

    @contextmanager
    def mutating_lock(_audit_root: Path) -> Generator[None]:
        (repository / "AGENTS.md").write_text(
            "# Changed while acquiring the lock\n",
            encoding="utf-8",
        )
        yield

    monkeypatch.setattr("edifice.coding_run._coding_run_lock", mutating_lock)
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Lock race",
            "--objective",
            "Reject changes during lock acquisition.",
            "--jira",
            "EDIFICE-132",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    run_path = vault_root / "20-work" / "operations" / "coding-runs" / "lock-race"
    assert result.exit_code != 0
    assert "Repository changed while preparing coding run." in result.output
    assert not run_path.exists()


def test_code_start_rolls_back_run_when_repository_changes_during_publication(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    original_rename = os.rename

    def mutate_after_rename(source: Path, destination: Path) -> None:
        original_rename(source, destination)
        (repository / "AGENTS.md").write_text(
            "# Changed during publication\n",
            encoding="utf-8",
        )

    monkeypatch.setattr("edifice.coding_run.os.rename", mutate_after_rename)
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Publication race",
            "--objective",
            "Roll back a stale published assignment.",
            "--jira",
            "EDIFICE-133",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    run_path = (
        vault_root / "20-work" / "operations" / "coding-runs" / "publication-race"
    )
    assert result.exit_code != 0
    assert "Repository changed while preparing coding run." in result.output
    assert not run_path.exists()


def test_code_start_reports_missing_workstream_registry(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository, include_registry=False)
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Missing registry",
            "--objective",
            "Report unavailable repository context.",
            "--jira",
            "EDIFICE-134",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    assert result.exit_code != 0
    assert "Workstream registry is unavailable at revision" in result.output
    assert not vault_root.exists()


def test_code_start_rolls_back_when_final_repository_snapshot_has_new_revision(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    original_revision = _run_git(repository, "rev-parse", "HEAD")
    snapshot_count = 0

    def repository_state(_repository_root: Path) -> tuple[str, str, bool]:
        nonlocal snapshot_count
        snapshot_count += 1
        revision = original_revision if snapshot_count < 4 else "b" * 40
        return "nahmad/example-codex", revision, True

    monkeypatch.setattr(
        "edifice.coding_run._repository_state",
        repository_state,
        raising=False,
    )
    vault_root = tmp_path / "vault"

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "code",
            "start",
            "--name",
            "Revision race",
            "--objective",
            "Reject a new final repository revision.",
            "--jira",
            "EDIFICE-135",
            "--repo",
            str(repository),
            "--workstream",
            "example",
            "--mode",
            "design",
            "--learning-level",
            "brief",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-20",
        ],
    )

    run_path = vault_root / "20-work" / "operations" / "coding-runs" / "revision-race"
    assert result.exit_code != 0
    assert "Repository changed while preparing coding run." in result.output
    assert not run_path.exists()
