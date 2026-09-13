import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

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
) -> dict[str, object]:
    files = {
        "AGENTS.md": "# Repository instructions\n",
        "docs/agent-context.md": "# Agent context\n",
        "docs/engineering/owner-practices.md": "# Owner practices\n",
        "docs/workstreams/example.md": "# Example workstream\n",
        "src/AGENTS.md": "# Source instructions\n",
        "src/example.py": 'MESSAGE = "unchanged"\n',
    }
    for relative_path, content in files.items():
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

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
    assert coding_run["writable_paths"] == ["src/example.py"]
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
    assert assignment["writable_paths"] == ["src/example.py"]
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
