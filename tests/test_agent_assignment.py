import copy
import json
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
        match="Assignment is missing required context",
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

    def git_value(_repository_root: Path, *arguments: str) -> str:
        if arguments == ("branch", "--show-current"):
            return "nahmad/meeting-notes-codex"
        if arguments == ("rev-parse", "HEAD"):
            return "a" * 40
        raise AssertionError(f"Unexpected Git arguments: {arguments}")

    monkeypatch.setattr("edifice.agent_assignment._git_value", git_value)

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
