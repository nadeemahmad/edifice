import io
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner
from pytest import MonkeyPatch

from edifice.cli import cli
from edifice.coding_launch import (
    CodexLaunchRetryableError,
    CodexTask,
    CodexTaskStartedError,
    launch_with_codex_app,
)


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


def _create_repository(repository: Path) -> None:
    files = {
        "AGENTS.md": "# Repository instructions\n",
        "docs/agent-context.md": "# Agent context\n",
        "docs/engineering/owner-practices.md": "# Owner practices\n",
        "docs/workstreams/example.md": "# Example workstream\n",
        "src/example.py": 'MESSAGE = "unchanged"\n',
    }
    for relative_path, content in files.items():
        path = repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    registry = {
        "schema_version": 1,
        "integration_owned_paths": [],
        "workstreams": [
            {
                "id": "example",
                "title": "Example",
                "status": "active",
                "mode": "design",
                "context": "docs/workstreams/example.md",
                "owned_paths": ["src/example.py"],
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


def _start_run(
    runner: CliRunner,
    *,
    vault_root: Path,
    audit_root: Path,
    repository: Path,
) -> None:
    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "start",
            "--name",
            "Launch example",
            "--objective",
            "Create one visible Codex task.",
            "--jira",
            "EDIFICE-200",
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
    assert result.exit_code == 0


def test_code_launch_dry_run_previews_task_without_contacting_codex(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    before = run_path.read_bytes()

    def fail_if_launched(**_arguments: object) -> object:
        raise AssertionError("dry run contacted Codex")

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        fail_if_launched,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "--dry-run",
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
    )

    assert result.exit_code == 0
    assert result.output == (
        "Task: EDIFICE-200: Launch example.\n"
        f"Project: inferred by Codex from {repository}.\n"
        f"Worktree: {repository}.\n"
        "Model: gpt-test.\n"
        "Sandbox: read-only.\n"
        "Dry run: no Codex task created.\n"
    )
    assert run_path.read_bytes() == before


def test_code_launch_confirmed_records_verified_codex_task(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    launch_arguments: dict[str, object] = {}

    def launch_with_codex_app(**arguments: object) -> object:
        launch_arguments.update(arguments)
        return SimpleNamespace(
            thread_id="thread-123",
            turn_id="turn-456",
            project_id="project-edifice",
            cwd=repository,
            instruction_sources=(repository / "AGENTS.md",),
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_with_codex_app,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._now",
        lambda: "2026-09-13T18:00:00+00:00",
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code == 0
    assert "Launch this Codex task? [y/N]: y" in result.output
    assert "Launched Codex task: thread-123." in result.output
    assert "Project ID: project-edifice." in result.output
    assert launch_arguments["repository"] == repository
    assert launch_arguments["model"] == "gpt-test"
    assert launch_arguments["sandbox"] == "read-only"
    assert "Create one visible Codex task." in str(launch_arguments["prompt"])
    assert "docs/agent-context.md" in str(launch_arguments["prompt"])
    assert assignment_state == {
        "status": "launched",
        "path": "agent-assignment.preview.json",
        "runtime": "codex-app-server",
        "model": "gpt-test",
        "sandbox": "read-only",
        "launch_started_at": "2026-09-13T18:00:00+00:00",
        "thread_id": "thread-123",
        "turn_id": "turn-456",
        "project_id": "project-edifice",
        "cwd": str(repository),
        "launched_at": "2026-09-13T18:00:00+00:00",
        "instruction_sources": [str(repository / "AGENTS.md")],
    }


def test_code_launch_records_intent_before_contacting_codex(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )

    def inspect_launch_intent(**_arguments: object) -> object:
        coding_run = json.loads(run_path.read_text(encoding="utf-8"))
        assert coding_run["assignment"] == {
            "status": "launching",
            "path": "agent-assignment.preview.json",
            "runtime": "codex-app-server",
            "model": "gpt-test",
            "sandbox": "read-only",
            "launch_started_at": "2026-09-13T17:45:00+00:00",
            "thread_id": None,
            "turn_id": None,
            "project_id": None,
            "cwd": str(repository),
            "instruction_sources": [],
        }
        return SimpleNamespace(
            thread_id="thread-123",
            turn_id="turn-456",
            project_id="project-edifice",
            cwd=repository,
            instruction_sources=(repository / "AGENTS.md",),
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        inspect_launch_intent,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._now",
        lambda: "2026-09-13T17:45:00+00:00",
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    assert result.exit_code == 0


def test_code_launch_records_thread_identity_during_app_launch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    partial_task = CodexTask(
        thread_id="thread-immediate",
        turn_id=None,
        project_id=None,
        cwd=None,
        instruction_sources=(),
    )

    def launch_and_report_thread(**arguments: object) -> object:
        callback = arguments["on_thread_started"]
        assert callable(callback)
        callback(partial_task)
        coding_run = json.loads(run_path.read_text(encoding="utf-8"))
        assignment_state = coding_run["assignment"]
        assert assignment_state["status"] == "launching"
        assert assignment_state["thread_id"] == "thread-immediate"
        raise CodexTaskStartedError(
            "Opening turn failed.",
            partial_task,
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_and_report_thread,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    assert result.exit_code != 0
    assert "Recorded task thread-immediate for recovery." in result.output


class _RecordingInput(io.StringIO):
    def close(self) -> None:
        self.flush()


class _FakeAppServerProcess:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.stdin = _RecordingInput()
        self.stdout = io.StringIO(
            "".join(json.dumps(response) + "\n" for response in responses)
        )
        self.stderr = io.StringIO()
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0


class _BrokenInput(_RecordingInput):
    def write(self, text: str) -> int:
        del text
        raise BrokenPipeError("proxy input closed")


class _WaitFailureProcess(_FakeAppServerProcess):
    def wait(self, timeout: float | None = None) -> int:
        del timeout
        raise OSError("wait failed")


class _StalledOutput(io.StringIO):
    def readline(self, size: int = -1) -> str:
        del size
        time.sleep(1)
        return ""


class _SlowNotificationOutput(io.StringIO):
    def __init__(self, lines: list[dict[str, object]], delay: float) -> None:
        super().__init__("")
        self._lines = [json.dumps(line) + "\n" for line in lines]
        self._delay = delay

    def readline(self, size: int = -1) -> str:
        del size
        time.sleep(self._delay)
        if not self._lines:
            return ""
        return self._lines.pop(0)


def test_codex_app_launcher_starts_named_project_task_and_opening_turn(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "name": "Edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "method": "thread/started",
            "params": {"thread": {"id": "thread-123"}},
        },
        {
            "id": 3,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": "gpt-test",
                "sandbox": {"type": "readOnly"},
                "thread": {
                    "id": "thread-123",
                    "cwd": str(repository),
                    "projectId": "project-edifice",
                },
            },
        },
        {"id": 4, "result": {}},
        {
            "id": 5,
            "result": {
                "turn": {
                    "id": "turn-456",
                }
            },
        },
    ]
    process = _FakeAppServerProcess(responses)
    command: list[str] = []

    def start_process(
        arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        command.extend(arguments)
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    task = launch_with_codex_app(
        codex_binary="codex-test",
        title="EDIFICE-200: Launch example",
        repository=repository,
        model="gpt-test",
        sandbox="read-only",
        prompt="Bounded assignment prompt.",
    )

    requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert command == ["codex-test", "app-server", "proxy"]
    assert requests == [
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "capabilities": {
                    "experimentalApi": True,
                },
                "clientInfo": {
                    "name": "edifice",
                    "title": "Edifice",
                    "version": "0.1.0",
                },
            },
        },
        {"method": "initialized"},
        {
            "id": 2,
            "method": "project/list",
            "params": {
                "limit": 100,
            },
        },
        {
            "id": 3,
            "method": "thread/start",
            "params": {
                "approvalPolicy": "on-request",
                "cwd": str(repository),
                "ephemeral": False,
                "model": "gpt-test",
                "projectId": "project-edifice",
                "sandbox": "read-only",
            },
        },
        {
            "id": 4,
            "method": "thread/name/set",
            "params": {
                "name": "EDIFICE-200: Launch example",
                "threadId": "thread-123",
            },
        },
        {
            "id": 5,
            "method": "turn/start",
            "params": {
                "input": [
                    {
                        "type": "text",
                        "text": "Bounded assignment prompt.",
                    }
                ],
                "threadId": "thread-123",
            },
        },
    ]
    assert task.thread_id == "thread-123"
    assert task.turn_id == "turn-456"
    assert task.project_id == "project-edifice"
    assert task.cwd == repository
    assert task.instruction_sources == (repository / "AGENTS.md",)


def test_codex_app_launcher_follows_project_list_pagination(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [],
                "nextCursor": "page-2",
            },
        },
        {
            "id": 3,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "id": 4,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": "gpt-test",
                "sandbox": {"type": "readOnly"},
                "thread": {
                    "id": "thread-123",
                    "cwd": str(repository),
                    "projectId": "project-edifice",
                },
            },
        },
        {"id": 5, "result": {}},
        {"id": 6, "result": {"turn": {"id": "turn-456"}}},
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    task = launch_with_codex_app(
        codex_binary="codex-test",
        title="EDIFICE-200: Launch example",
        repository=repository,
        model="gpt-test",
        sandbox="read-only",
        prompt="Bounded assignment prompt.",
    )

    requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert requests[2] == {
        "id": 2,
        "method": "project/list",
        "params": {"limit": 100},
    }
    assert requests[3] == {
        "id": 3,
        "method": "project/list",
        "params": {
            "cursor": "page-2",
            "limit": 100,
        },
    }
    assert task.thread_id == "thread-123"


def test_codex_app_launcher_does_not_match_sibling_worktree_project(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "main"
    repository.mkdir()
    _run_git(repository, "init", "-b", "main")
    _run_git(repository, "config", "user.email", "test@example.com")
    _run_git(repository, "config", "user.name", "Test User")
    (repository / "README.md").write_text("# Repository\n", encoding="utf-8")
    _run_git(repository, "add", "README.md")
    _run_git(repository, "commit", "-m", "Initial repository")
    target = tmp_path / "target"
    sibling = tmp_path / "sibling"
    _run_git(repository, "worktree", "add", "-b", "target", str(target))
    _run_git(repository, "worktree", "add", "-b", "sibling", str(sibling))
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-sibling",
                        "roots": [{"path": str(sibling)}],
                    }
                ],
                "nextCursor": None,
            },
        },
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(
        CodexLaunchRetryableError,
        match="No Codex project contains repository",
    ):
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=target,
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )


def test_codex_app_launcher_rejects_repeated_project_cursor(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [],
                "nextCursor": "repeat",
            },
        },
        {
            "id": 3,
            "result": {
                "data": [],
                "nextCursor": "repeat",
            },
        },
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(
        CodexLaunchRetryableError,
        match="Codex project list repeated cursor",
    ):
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=tmp_path / "repository",
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )


def test_codex_app_launcher_times_out_when_proxy_stalls(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    process = _FakeAppServerProcess([])
    process.stdout = _StalledOutput()

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    monkeypatch.setattr(
        "edifice.coding_launch.RPC_TIMEOUT_SECONDS",
        0.01,
    )

    with pytest.raises(
        click.ClickException,
        match="Codex app-server timed out during initialize",
    ):
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=tmp_path / "repository",
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )


def test_codex_app_launcher_marks_pre_thread_broken_pipe_retryable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    process = _FakeAppServerProcess([])
    process.stdin = _BrokenInput()

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(
        CodexLaunchRetryableError,
        match="Cannot write to Codex app-server proxy",
    ):
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=tmp_path / "repository",
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )


def test_codex_app_launcher_cleanup_error_does_not_replace_success(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "id": 3,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": "gpt-test",
                "sandbox": {"type": "readOnly"},
                "thread": {
                    "id": "thread-123",
                    "cwd": str(repository),
                    "projectId": "project-edifice",
                },
            },
        },
        {"id": 4, "result": {}},
        {"id": 5, "result": {"turn": {"id": "turn-456"}}},
    ]
    process = _WaitFailureProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _WaitFailureProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    task = launch_with_codex_app(
        codex_binary="codex-test",
        title="EDIFICE-200: Launch example",
        repository=repository,
        model="gpt-test",
        sandbox="read-only",
        prompt="Bounded assignment prompt.",
    )

    assert task.thread_id == "thread-123"
    assert task.turn_id == "turn-456"


def test_codex_app_launcher_notifications_do_not_reset_rpc_deadline(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    process = _FakeAppServerProcess([])
    process.stdout = _SlowNotificationOutput(
        [
            {"method": "one"},
            {"method": "two"},
            {"method": "three"},
            {"id": 1, "result": {}},
        ],
        delay=0.01,
    )

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )
    monkeypatch.setattr(
        "edifice.coding_launch.RPC_TIMEOUT_SECONDS",
        0.015,
    )

    with pytest.raises(
        click.ClickException,
        match="Codex app-server timed out during initialize",
    ):
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=tmp_path / "repository",
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )


def test_code_launch_rejects_stale_repository_before_contacting_codex(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    (repository / "src" / "example.py").write_text(
        'MESSAGE = "changed"\n',
        encoding="utf-8",
    )
    _run_git(repository, "add", "src/example.py")
    _run_git(repository, "commit", "-m", "Advance repository")

    def fail_if_launched(**_arguments: object) -> object:
        raise AssertionError("stale assignment contacted Codex")

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        fail_if_launched,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assert result.exit_code != 0
    assert "Repository changed since coding run" in result.output
    assert coding_run["assignment"]["status"] == "not-launched"


def test_code_launch_dry_run_rejects_stale_repository(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    (repository / "src" / "example.py").write_text(
        'MESSAGE = "changed"\n',
        encoding="utf-8",
    )
    _run_git(repository, "add", "src/example.py")
    _run_git(repository, "commit", "-m", "Advance repository")

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "--dry-run",
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
    )

    assert result.exit_code != 0
    assert "Repository changed since coding run" in result.output
    assert "Dry run: no Codex task created." not in result.output


def test_code_launch_retry_returns_recorded_task_without_contacting_codex(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    launch_count = 0

    def launch_once(**_arguments: object) -> object:
        nonlocal launch_count
        launch_count += 1
        if launch_count > 1:
            raise AssertionError("retry contacted Codex")
        return SimpleNamespace(
            thread_id="thread-123",
            turn_id="turn-456",
            project_id="project-edifice",
            cwd=repository,
            instruction_sources=(repository / "AGENTS.md",),
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_once,
    )
    first = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )
    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    before_retry = run_path.read_bytes()

    retry = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
    )

    assert first.exit_code == 0
    assert retry.exit_code == 0
    assert retry.output == (
        "Existing Codex task: thread-123.\nProject ID: project-edifice.\n"
    )
    assert launch_count == 1
    assert run_path.read_bytes() == before_retry


def test_code_launch_records_task_that_fails_project_verification(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    wrong_repository = tmp_path / "wrong-repository"

    def launch_wrong_task(**_arguments: object) -> object:
        return SimpleNamespace(
            thread_id="thread-wrong",
            turn_id="turn-wrong",
            project_id="project-wrong",
            cwd=wrong_repository,
            instruction_sources=(),
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_wrong_task,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._now",
        lambda: "2026-09-13T18:30:00+00:00",
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code != 0
    assert "Codex task worktree mismatch" in result.output
    assert "Recorded task thread-wrong for recovery." in result.output
    assert assignment_state["status"] == "launch-needs-review"
    assert assignment_state["thread_id"] == "thread-wrong"
    assert assignment_state["project_id"] == "project-wrong"
    assert assignment_state["launch_error"].startswith("Codex task worktree mismatch")


def test_codex_app_launcher_preserves_thread_when_opening_turn_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "id": 3,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": "gpt-test",
                "sandbox": {"type": "readOnly"},
                "thread": {
                    "id": "thread-partial",
                    "cwd": str(repository),
                    "projectId": "project-edifice",
                },
            },
        },
        {
            "id": 4,
            "error": {
                "message": "cannot set thread name",
            },
        },
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(click.ClickException) as caught:
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=repository,
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )

    task = getattr(caught.value, "task", None)
    assert task is not None
    assert task.thread_id == "thread-partial"
    assert task.project_id == "project-edifice"
    assert task.cwd == repository


def test_codex_app_launcher_preserves_thread_when_project_is_unassigned(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "id": 3,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": "gpt-test",
                "sandbox": {"type": "readOnly"},
                "thread": {
                    "id": "thread-unassigned",
                    "cwd": str(repository),
                    "projectId": None,
                },
            },
        },
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(click.ClickException) as caught:
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=repository,
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )

    task = getattr(caught.value, "task", None)
    assert task is not None
    assert task.thread_id == "thread-unassigned"
    assert task.project_id is None


def test_codex_app_launcher_revalidates_repository_before_opening_turn(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "id": 3,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": "gpt-test",
                "sandbox": {"type": "readOnly"},
                "thread": {
                    "id": "thread-partial",
                    "cwd": str(repository),
                    "projectId": "project-edifice",
                },
            },
        },
        {"id": 4, "result": {}},
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    def reject_stale_repository() -> None:
        raise click.ClickException("Repository changed during coding launch.")

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(click.ClickException) as caught:
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=repository,
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
            before_turn=reject_stale_repository,
        )

    requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    task = getattr(caught.value, "task", None)
    assert task is not None
    assert task.thread_id == "thread-partial"
    assert not any(request.get("method") == "turn/start" for request in requests)


@pytest.mark.parametrize(
    ("effective_model", "effective_sandbox", "expected_error"),
    [
        ("gpt-other", "readOnly", "Codex effective model mismatch"),
        ("gpt-test", "workspaceWrite", "Codex effective sandbox mismatch"),
    ],
)
def test_codex_app_launcher_rejects_effective_configuration_mismatch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    effective_model: str,
    effective_sandbox: str,
    expected_error: str,
) -> None:
    repository = tmp_path / "repository"
    responses: list[dict[str, object]] = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "id": "project-edifice",
                        "roots": [{"path": str(repository)}],
                    }
                ],
                "nextCursor": None,
            },
        },
        {
            "id": 3,
            "result": {
                "cwd": str(repository),
                "instructionSources": [str(repository / "AGENTS.md")],
                "model": effective_model,
                "sandbox": {"type": effective_sandbox},
                "thread": {
                    "id": "thread-mismatch",
                    "cwd": str(repository),
                    "projectId": "project-edifice",
                },
            },
        },
        {"id": 4, "result": {}},
        {"id": 5, "result": {"turn": {"id": "turn-456"}}},
    ]
    process = _FakeAppServerProcess(responses)

    def start_process(
        _arguments: list[str],
        **_options: object,
    ) -> _FakeAppServerProcess:
        return process

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        start_process,
    )

    with pytest.raises(click.ClickException, match=expected_error):
        launch_with_codex_app(
            codex_binary="codex-test",
            title="EDIFICE-200: Launch example",
            repository=repository,
            model="gpt-test",
            sandbox="read-only",
            prompt="Bounded assignment prompt.",
        )

    requests = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
    assert not any(request.get("method") == "turn/start" for request in requests)


def test_code_launch_records_partial_task_when_opening_turn_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    partial_task = CodexTask(
        thread_id="thread-partial",
        turn_id="",
        project_id="project-edifice",
        cwd=repository,
        instruction_sources=(repository / "AGENTS.md",),
    )

    def fail_after_thread_start(**_arguments: object) -> object:
        raise CodexTaskStartedError(
            "Codex app-server rejected turn/start.",
            partial_task,
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        fail_after_thread_start,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._now",
        lambda: "2026-09-13T19:00:00+00:00",
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code != 0
    assert "Recorded task thread-partial for recovery." in result.output
    assert assignment_state["status"] == "launch-needs-review"
    assert assignment_state["thread_id"] == "thread-partial"
    assert assignment_state["turn_id"] == ""
    assert assignment_state["launch_error"] == ("Codex app-server rejected turn/start.")


def test_code_launch_records_task_when_repository_changes_during_turn_start(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )

    def launch_then_change_repository(**_arguments: object) -> object:
        (repository / "src" / "example.py").write_text(
            'MESSAGE = "changed during launch"\n',
            encoding="utf-8",
        )
        _run_git(repository, "add", "src/example.py")
        _run_git(repository, "commit", "-m", "Change during launch")
        return SimpleNamespace(
            thread_id="thread-stale",
            turn_id="turn-stale",
            project_id="project-edifice",
            cwd=repository,
            instruction_sources=(repository / "AGENTS.md",),
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_then_change_repository,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code != 0
    assert "Repository changed since coding run" in result.output
    assert "Recorded task thread-stale for recovery." in result.output
    assert assignment_state["status"] == "launch-needs-review"
    assert assignment_state["thread_id"] == "thread-stale"


def test_code_launch_marks_proxy_start_failure_retryable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )

    def fail_to_start_proxy(_arguments: list[str]) -> object:
        raise OSError("app-server unavailable")

    monkeypatch.setattr(
        "edifice.coding_launch._start_proxy",
        fail_to_start_proxy,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code != 0
    assert "Cannot start Codex app-server proxy" in result.output
    assert assignment_state["status"] == "launch-retryable"
    assert assignment_state["thread_id"] is None
    assert assignment_state["launch_error"].endswith("app-server unavailable")


def test_code_launch_records_recovery_when_final_persistence_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    task = CodexTask(
        thread_id="thread-persist",
        turn_id="turn-persist",
        project_id="project-edifice",
        cwd=repository,
        instruction_sources=(repository / "AGENTS.md",),
    )

    def launch_task(**arguments: object) -> object:
        callback = arguments["on_thread_started"]
        assert callable(callback)
        callback(
            CodexTask(
                thread_id=task.thread_id,
                turn_id=None,
                project_id=None,
                cwd=None,
                instruction_sources=(),
            )
        )
        return task

    write_count = 0

    def fail_final_write(path: Path, value: dict[str, object]) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 3:
            raise OSError("final persistence failed")
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_task,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._replace_json_atomically",
        fail_final_write,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code != 0
    assert "Cannot record completed Codex task thread-persist" in result.output
    assert assignment_state["status"] == "launch-needs-review"
    assert assignment_state["thread_id"] == "thread-persist"
    assert assignment_state["launch_error"].endswith("final persistence failed")


def test_code_launch_recovery_file_survives_repeated_main_record_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    partial_task = CodexTask(
        thread_id="thread-durable",
        turn_id=None,
        project_id=None,
        cwd=None,
        instruction_sources=(),
    )

    def launch_with_failed_callback(**arguments: object) -> object:
        callback = arguments["on_thread_started"]
        assert callable(callback)
        try:
            callback(partial_task)
        except click.ClickException as error:
            raise CodexTaskStartedError(error.message, partial_task) from error
        raise AssertionError("callback unexpectedly succeeded")

    write_count = 0

    def fail_after_launch_intent(path: Path, value: dict[str, object]) -> None:
        nonlocal write_count
        write_count += 1
        if write_count >= 2:
            raise OSError("main record unavailable")
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_with_failed_callback,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._replace_json_atomically",
        fail_after_launch_intent,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_directory = (
        vault_root / "20-work" / "operations" / "coding-runs" / "launch-example"
    )
    recovery = json.loads(
        (run_directory / "launch-recovery.json").read_text(encoding="utf-8")
    )
    coding_run = json.loads(
        (run_directory / "coding-run.json").read_text(encoding="utf-8")
    )

    assert result.exit_code != 0
    assert "thread-durable" in result.output
    assert "launch-recovery.json" in result.output
    assert recovery["thread_id"] == "thread-durable"
    assert coding_run["assignment"]["status"] == "launching"


def test_code_launch_records_thread_when_recovery_file_write_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    partial_task = CodexTask(
        thread_id="thread-recovery-failed",
        turn_id=None,
        project_id=None,
        cwd=None,
        instruction_sources=(),
    )

    def launch_with_failed_recovery(**arguments: object) -> object:
        callback = arguments["on_thread_started"]
        assert callable(callback)
        try:
            callback(partial_task)
        except click.ClickException as error:
            raise CodexTaskStartedError(error.message, partial_task) from error
        raise AssertionError("callback unexpectedly succeeded")

    def fail_recovery_file(
        _path: Path,
        **_arguments: object,
    ) -> None:
        raise OSError("recovery file unavailable")

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_with_failed_recovery,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._write_launch_recovery",
        fail_recovery_file,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    run_path = (
        vault_root
        / "20-work"
        / "operations"
        / "coding-runs"
        / "launch-example"
        / "coding-run.json"
    )
    coding_run = json.loads(run_path.read_text(encoding="utf-8"))
    assignment_state = coding_run["assignment"]

    assert result.exit_code != 0
    assert "thread-recovery-failed" in result.output
    assert assignment_state["status"] == "launch-needs-review"
    assert assignment_state["thread_id"] == "thread-recovery-failed"


def test_code_launch_does_not_claim_recovery_when_all_recovery_writes_fail(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _create_repository(repository)
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    _start_run(
        runner,
        vault_root=vault_root,
        audit_root=audit_root,
        repository=repository,
    )
    partial_task = CodexTask(
        thread_id="thread-undurable",
        turn_id=None,
        project_id=None,
        cwd=None,
        instruction_sources=(),
    )

    def launch_with_failed_recovery(**arguments: object) -> object:
        callback = arguments["on_thread_started"]
        assert callable(callback)
        try:
            callback(partial_task)
        except click.ClickException as error:
            raise CodexTaskStartedError(error.message, partial_task) from error
        raise AssertionError("callback unexpectedly succeeded")

    write_count = 0

    def fail_main_recovery(path: Path, value: dict[str, object]) -> None:
        nonlocal write_count
        write_count += 1
        if write_count >= 2:
            raise OSError("main recovery unavailable")
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def fail_recovery_file(
        _path: Path,
        **_arguments: object,
    ) -> None:
        raise OSError("recovery file unavailable")

    monkeypatch.setattr(
        "edifice.coding_launch.launch_with_codex_app",
        launch_with_failed_recovery,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._replace_json_atomically",
        fail_main_recovery,
    )
    monkeypatch.setattr(
        "edifice.coding_launch._write_launch_recovery",
        fail_recovery_file,
    )

    result = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "code",
            "launch",
            "launch-example",
            "--model",
            "gpt-test",
        ],
        input="y\n",
    )

    assert result.exit_code != 0
    assert "thread-undurable" in result.output
    assert "could not be durably recorded" in result.output
    assert "is recorded in launch-recovery.json" not in result.output
