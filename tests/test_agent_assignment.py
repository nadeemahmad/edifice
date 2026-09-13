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


def test_agent_assignment_command_validates_current_checkout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assignment = _active_assignment()
    assignment["branch"] = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assignment["base_revision"] = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assignment_path = tmp_path / "assignment.json"
    assignment_path.write_text(json.dumps(assignment), encoding="utf-8")

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
