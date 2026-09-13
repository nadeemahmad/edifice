import copy
import json
import subprocess
from pathlib import Path

import pytest

from edifice.agent_assignment import (
    AssignmentValidationError,
    main,
    validate_agent_assignment,
)

REPOSITORY_ROOT = Path(__file__).parents[1]


def _active_assignment() -> dict[str, object]:
    assignment = json.loads(
        (
            REPOSITORY_ROOT / "docs" / "engineering" / "agent-assignment.example.json"
        ).read_text(encoding="utf-8")
    )
    assignment["assignment_kind"] = "active"
    assignment["base_revision"] = "a" * 40
    assignment["worktree"] = str(REPOSITORY_ROOT)
    return assignment


def _registry() -> dict[str, object]:
    return json.loads(
        (REPOSITORY_ROOT / "docs" / "workstreams" / "registry.json").read_text(
            encoding="utf-8"
        )
    )


def test_agent_assignment_accepts_registered_feature_write_scope() -> None:
    assignment = validate_agent_assignment(
        assignment=_active_assignment(),
        registry=_registry(),
        repository_root=REPOSITORY_ROOT,
    )

    assert assignment["workstream"] == "meeting-notes"


def test_agent_assignment_rejects_integration_owned_write() -> None:
    assignment = copy.deepcopy(_active_assignment())
    assignment["writable_paths"] = ["README.md"]

    with pytest.raises(
        AssignmentValidationError,
        match="Writable path is integration-owned: README.md",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=_registry(),
            repository_root=REPOSITORY_ROOT,
        )


def test_agent_assignment_rejects_different_worktree() -> None:
    assignment = _active_assignment()
    assignment["worktree"] = "/tmp/different-edifice-worktree"

    with pytest.raises(
        AssignmentValidationError,
        match="Assignment worktree does not match repository",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=_registry(),
            repository_root=REPOSITORY_ROOT,
        )


def test_agent_assignment_requires_repository_and_workstream_context() -> None:
    assignment = _active_assignment()
    assignment["context_paths"] = []

    with pytest.raises(
        AssignmentValidationError,
        match="Assignment is missing governing instructions or required context",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=_registry(),
            repository_root=REPOSITORY_ROOT,
        )


def test_agent_assignment_rejects_abbreviated_revision() -> None:
    assignment = _active_assignment()
    assignment["base_revision"] = "a" * 7

    with pytest.raises(
        AssignmentValidationError,
        match="Active assignment has an invalid revision.",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=_registry(),
            repository_root=REPOSITORY_ROOT,
            expected_revision="a" * 40,
        )


def test_agent_assignment_rejects_writable_path_resolving_outside_repository(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    outside = tmp_path / "outside"
    repository.mkdir()
    outside.mkdir()
    (outside / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository / "src").symlink_to("../outside", target_is_directory=True)
    context_paths = [
        "AGENTS.md",
        "docs/agent-context.md",
        "docs/engineering/owner-practices.md",
        "docs/workstreams/example.md",
    ]
    for relative_path in context_paths:
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Context\n", encoding="utf-8")
    assignment = _active_assignment()
    assignment.update(
        {
            "workstream": "example",
            "worktree": str(repository),
            "context_paths": context_paths,
            "writable_paths": ["src/example.py"],
        }
    )
    registry: dict[str, object] = {
        "schema_version": 1,
        "integration_owned_paths": [],
        "workstreams": [
            {
                "id": "example",
                "context": "docs/workstreams/example.md",
                "owned_paths": ["src/example.py"],
            }
        ],
    }

    with pytest.raises(
        AssignmentValidationError,
        match="Writable path resolves outside repository: src/example.py",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=registry,
            repository_root=repository,
        )


def test_agent_assignment_rejects_write_scope_for_read_only_mode() -> None:
    assignment = _active_assignment()
    assignment["mode"] = "review"

    with pytest.raises(
        AssignmentValidationError,
        match="Read-only assignment mode cannot declare writable paths: review",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=_registry(),
            repository_root=REPOSITORY_ROOT,
        )


def test_agent_assignment_requires_nested_instructions_for_writable_paths() -> None:
    assignment = _active_assignment()
    assignment.update(
        {
            "workstream": "coding-workflow",
            "context_paths": [
                "AGENTS.md",
                "docs/agent-context.md",
                "docs/engineering/owner-practices.md",
                "docs/workstreams/coding-workflow.md",
            ],
            "writable_paths": [
                "vault-template/20-work/operations/coding-runs/AGENTS.md"
            ],
        }
    )

    with pytest.raises(
        AssignmentValidationError,
        match="Assignment is missing governing instructions",
    ):
        validate_agent_assignment(
            assignment=assignment,
            registry=_registry(),
            repository_root=REPOSITORY_ROOT,
        )


def test_agent_assignment_command_validates_feature_checkout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment = _active_assignment()
    assignment["branch"] = "nahmad/meeting-notes-codex"
    assignment["base_revision"] = "a" * 40
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment), encoding="utf-8")

    def clean_repository_state(_repository_root: Path) -> tuple[str, str, bool]:
        return (
            "nahmad/meeting-notes-codex",
            "a" * 40,
            True,
        )

    monkeypatch.setattr(
        "edifice.agent_assignment._repository_state",
        clean_repository_state,
    )

    def load_registry(
        _repository_root: Path,
        _revision: str,
    ) -> object:
        return _registry()

    monkeypatch.setattr(
        "edifice.agent_assignment._load_registry_at_revision",
        load_registry,
    )

    exit_code = main(
        [
            str(assignment_path),
            "--registry",
            str(REPOSITORY_ROOT / "docs" / "workstreams" / "registry.json"),
            "--repository",
            str(REPOSITORY_ROOT),
        ]
    )

    assert exit_code == 0
    assert "Valid active assignment: meeting-notes" in capsys.readouterr().out


def test_agent_assignment_command_rejects_dirty_checkout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assignment = _active_assignment()
    assignment["branch"] = "nahmad/meeting-notes-codex"
    assignment["base_revision"] = "a" * 40
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment), encoding="utf-8")

    def dirty_repository_state(_repository_root: Path) -> tuple[str, str, bool]:
        return (
            "nahmad/meeting-notes-codex",
            "a" * 40,
            False,
        )

    monkeypatch.setattr(
        "edifice.agent_assignment._repository_state",
        dirty_repository_state,
    )

    exit_code = main(
        [
            str(assignment_path),
            "--registry",
            str(REPOSITORY_ROOT / "docs" / "workstreams" / "registry.json"),
            "--repository",
            str(REPOSITORY_ROOT),
        ]
    )

    assert exit_code == 1
    assert (
        "Invalid assignment: Repository working tree is not clean."
        in capsys.readouterr().err
    )


def test_agent_assignment_command_rechecks_repository_before_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assignment = _active_assignment()
    assignment["branch"] = branch
    assignment["base_revision"] = revision
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    snapshot_count = 0

    def changing_repository_state(_repository_root: Path) -> tuple[str, str, bool]:
        nonlocal snapshot_count
        snapshot_count += 1
        return branch, revision, snapshot_count == 1

    monkeypatch.setattr(
        "edifice.agent_assignment._repository_state",
        changing_repository_state,
    )

    exit_code = main(
        [
            str(assignment_path),
            "--registry",
            str(REPOSITORY_ROOT / "docs" / "workstreams" / "registry.json"),
            "--repository",
            str(REPOSITORY_ROOT),
        ]
    )

    assert exit_code == 1
    assert (
        "Invalid assignment: Repository changed during assignment validation."
        in capsys.readouterr().err
    )


def test_agent_assignment_command_rejects_noncanonical_registry(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assignment = _active_assignment()
    assignment["branch"] = branch
    assignment["base_revision"] = revision
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry()), encoding="utf-8")

    def clean_repository_state(_repository_root: Path) -> tuple[str, str, bool]:
        return branch, revision, True

    monkeypatch.setattr(
        "edifice.agent_assignment._repository_state",
        clean_repository_state,
    )

    exit_code = main(
        [
            str(assignment_path),
            "--registry",
            str(registry_path),
            "--repository",
            str(REPOSITORY_ROOT),
        ]
    )

    assert exit_code == 1
    assert (
        "Invalid assignment: Registry path must be the canonical repository "
        "registry." in capsys.readouterr().err
    )


def test_agent_assignment_command_uses_committed_registry_bytes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository = tmp_path / "repository"
    context_paths = [
        "AGENTS.md",
        "docs/agent-context.md",
        "docs/engineering/owner-practices.md",
        "docs/workstreams/example.md",
    ]
    for relative_path in [*context_paths, "src/example.py"]:
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Content\n", encoding="utf-8")
    registry: dict[str, object] = {
        "schema_version": 1,
        "integration_owned_paths": [],
        "workstreams": [
            {
                "id": "example",
                "context": "docs/workstreams/example.md",
                "owned_paths": ["src/example.py"],
            }
        ],
    }
    registry_path = repository / "docs" / "workstreams" / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    subprocess.run(
        ["git", "init", "-b", "nahmad/example-codex"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial repository"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assignment = {
        "schema_version": 1,
        "assignment_kind": "active",
        "assignment_id": "committed-registry",
        "workstream": "example",
        "mode": "implementation",
        "learning_level": "brief",
        "base_revision": revision,
        "branch": "nahmad/example-codex",
        "worktree": str(repository),
        "objective": "Use committed ownership.",
        "context_paths": context_paths,
        "writable_paths": ["src/example.py"],
        "required_checks": ["pytest"],
        "prohibited_effects": ["No external mutation."],
        "completion_criteria": ["Validation passes."],
    }
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment), encoding="utf-8")
    subprocess.run(
        [
            "git",
            "update-index",
            "--assume-unchanged",
            "docs/workstreams/registry.json",
        ],
        cwd=repository,
        check=True,
    )
    registry["integration_owned_paths"] = ["src/example.py"]
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    exit_code = main(
        [
            str(assignment_path),
            "--registry",
            str(registry_path),
            "--repository",
            str(repository),
        ]
    )

    assert exit_code == 0
    assert "Valid active assignment: example" in capsys.readouterr().out
