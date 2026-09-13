"""Launch governed coding runs into persistent Codex tasks."""

import fcntl
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from time import monotonic
from typing import TextIO, cast

import click

from edifice.agent_assignment import (
    AssignmentValidationError,
    validate_agent_assignment,
)
from edifice.coding_run import CODING_RUN_DIRECTORY, READ_ONLY_MODES

RUN_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RPC_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class CodingLaunchPreview:
    slug: str
    title: str
    repository: Path
    model: str
    sandbox: str
    thread_id: str | None
    project_id: str | None


@dataclass(frozen=True)
class CodexTask:
    thread_id: str
    turn_id: str | None
    project_id: str | None
    cwd: Path | None
    instruction_sources: tuple[Path, ...]


class CodexTaskStartedError(click.ClickException):
    """A Codex thread exists but launch did not complete."""

    def __init__(self, message: str, task: CodexTask) -> None:
        super().__init__(message)
        self.task = task


class CodexLaunchRetryableError(click.ClickException):
    """Launch failed before a Codex thread could have been created."""


@dataclass(frozen=True)
class CodingLaunchResult:
    thread_id: str
    project_id: str


@dataclass
class _AppServerConnection:
    process: subprocess.Popen[str]
    responses: Queue[str | None]
    stderr_lines: list[str]


def prepare_coding_launch(
    *,
    vault_root: Path,
    slug: str,
    model: str,
) -> CodingLaunchPreview:
    """Load one coding run and derive its Codex launch parameters."""
    normalized_slug = slug.strip().lower()
    if not RUN_SLUG_PATTERN.fullmatch(normalized_slug):
        raise click.ClickException(f"Invalid coding run: {slug}")
    normalized_model = model.strip()
    if not normalized_model:
        raise click.ClickException("Model must not be empty.")

    run_path = vault_root / CODING_RUN_DIRECTORY / normalized_slug / "coding-run.json"
    coding_run = _load_mapping(run_path, "coding run")
    assignment = _require_mapping(coding_run.get("assignment"), "assignment")
    status = assignment.get("status")
    if status == "launched":
        thread_id = _require_string(assignment, "thread_id")
        project_id = _require_string(assignment, "project_id")
        validate_launch = False
    elif status in {"not-launched", "launch-retryable"}:
        thread_id = None
        project_id = None
        validate_launch = True
    else:
        raise click.ClickException(f"Coding run is already launched: {normalized_slug}")
    repository_data = _require_mapping(coding_run.get("repository"), "repository")
    repository = Path(_require_string(repository_data, "path"))
    jira = _require_mapping(coding_run.get("jira"), "jira")
    title = f"{_require_string(jira, 'key')}: {_require_string(coding_run, 'name')}"
    mode = _require_string(coding_run, "active_mode")
    sandbox = "read-only" if mode in READ_ONLY_MODES else "workspace-write"
    if validate_launch:
        assignment_path = run_path.with_name("agent-assignment.preview.json")
        assignment_preview = _load_mapping(assignment_path, "agent assignment")
        _validate_launch_assignment(
            coding_run=coding_run,
            assignment=assignment_preview,
            repository=repository,
        )
    return CodingLaunchPreview(
        slug=normalized_slug,
        title=title,
        repository=repository,
        model=normalized_model,
        sandbox=sandbox,
        thread_id=thread_id,
        project_id=project_id,
    )


def launch_coding_run(
    *,
    vault_root: Path,
    audit_root: Path,
    slug: str,
    model: str,
    codex_binary: str,
) -> CodingLaunchResult:
    """Launch one validated run and record the returned Codex task."""
    preview = prepare_coding_launch(
        vault_root=vault_root,
        slug=slug,
        model=model,
    )
    run_directory = vault_root / CODING_RUN_DIRECTORY / preview.slug
    run_path = run_directory / "coding-run.json"
    assignment_path = run_directory / "agent-assignment.preview.json"
    with _launch_lock(audit_root):
        coding_run = _load_mapping(run_path, "coding run")
        assignment_state = _require_mapping(
            coding_run.get("assignment"),
            "assignment",
        )
        status = assignment_state.get("status")
        if status == "launched":
            thread_id = _require_string(assignment_state, "thread_id")
            project_id = _require_string(assignment_state, "project_id")
            return CodingLaunchResult(
                thread_id=thread_id,
                project_id=project_id,
            )
        if status not in {"not-launched", "launch-retryable"}:
            raise click.ClickException(
                f"Coding run launch requires recovery: {preview.slug}"
            )
        assignment = _load_mapping(assignment_path, "agent assignment")
        _validate_launch_assignment(
            coding_run=coding_run,
            assignment=assignment,
            repository=preview.repository,
        )
        launch_started_at = _now()
        launching_run = dict(coding_run)
        launching_state = _launching_state(
            repository=preview.repository,
            model=preview.model,
            sandbox=preview.sandbox,
            launch_started_at=launch_started_at,
        )
        launching_run["assignment"] = launching_state
        _replace_json_atomically(run_path, launching_run)

        def record_started_thread(task: CodexTask) -> None:
            thread_run = dict(launching_run)
            thread_state = dict(launching_state)
            thread_state.update(
                {
                    "thread_id": task.thread_id,
                    "turn_id": task.turn_id,
                    "project_id": task.project_id,
                    "cwd": str(task.cwd) if task.cwd is not None else None,
                    "instruction_sources": [
                        str(path) for path in task.instruction_sources
                    ],
                }
            )
            thread_run["assignment"] = thread_state
            try:
                _replace_json_atomically(run_path, thread_run)
            except OSError as error:
                raise click.ClickException(
                    f"Cannot record started Codex task {task.thread_id}: {error}"
                ) from error

        try:
            task = launch_with_codex_app(
                codex_binary=codex_binary,
                title=preview.title,
                repository=preview.repository,
                model=preview.model,
                sandbox=preview.sandbox,
                prompt=_launch_prompt(assignment),
                on_thread_started=record_started_thread,
                before_turn=lambda: _validate_launch_assignment(
                    coding_run=coding_run,
                    assignment=assignment,
                    repository=preview.repository,
                ),
            )
        except CodexTaskStartedError as error:
            updated_run = dict(coding_run)
            failed_state = _task_state(
                task=error.task,
                model=preview.model,
                sandbox=preview.sandbox,
                status="launch-needs-review",
                launch_started_at=launch_started_at,
            )
            failed_state["launch_error"] = error.message
            updated_run["assignment"] = failed_state
            _replace_json_atomically(run_path, updated_run)
            raise click.ClickException(
                f"{error.message} Recorded task {error.task.thread_id} for recovery."
            ) from error
        except CodexLaunchRetryableError as error:
            failed_run = dict(launching_run)
            failed_state = dict(launching_state)
            failed_state["status"] = "launch-retryable"
            failed_state["launch_error"] = error.message
            failed_run["assignment"] = failed_state
            _replace_json_atomically(run_path, failed_run)
            raise
        except click.ClickException as error:
            failed_run = dict(launching_run)
            failed_state = dict(launching_state)
            failed_state["status"] = "launch-needs-review"
            failed_state["launch_error"] = error.message
            failed_run["assignment"] = failed_state
            _replace_json_atomically(run_path, failed_run)
            raise
        try:
            _validate_launch_assignment(
                coding_run=coding_run,
                assignment=assignment,
                repository=preview.repository,
            )
            thread_id, project_id = _validate_task(task, preview.repository)
        except click.ClickException as error:
            updated_run = dict(coding_run)
            failed_state = _task_state(
                task=task,
                model=preview.model,
                sandbox=preview.sandbox,
                status="launch-needs-review",
                launch_started_at=launch_started_at,
            )
            failed_state["launch_error"] = error.message
            updated_run["assignment"] = failed_state
            _replace_json_atomically(run_path, updated_run)
            raise click.ClickException(
                f"{error.message} Recorded task {task.thread_id} for recovery."
            ) from error
        updated_run = dict(coding_run)
        updated_run["assignment"] = _task_state(
            task=task,
            model=preview.model,
            sandbox=preview.sandbox,
            status="launched",
            launch_started_at=launch_started_at,
        )
        try:
            _replace_json_atomically(run_path, updated_run)
        except OSError as error:
            recovery_run = dict(coding_run)
            recovery_state = _task_state(
                task=task,
                model=preview.model,
                sandbox=preview.sandbox,
                status="launch-needs-review",
                launch_started_at=launch_started_at,
            )
            recovery_state["launch_error"] = (
                f"Cannot record completed Codex task: {error}"
            )
            recovery_run["assignment"] = recovery_state
            try:
                _replace_json_atomically(run_path, recovery_run)
            except OSError as recovery_error:
                raise click.ClickException(
                    "Cannot record completed Codex task "
                    f"{task.thread_id}: {error}. "
                    "The durable launching record retains the thread ID; "
                    f"recovery update also failed: {recovery_error}"
                ) from recovery_error
            raise click.ClickException(
                f"Cannot record completed Codex task {task.thread_id}: {error}. "
                "Recorded the task for recovery."
            ) from error
    return CodingLaunchResult(
        thread_id=thread_id,
        project_id=project_id,
    )


def _task_state(
    *,
    task: CodexTask,
    model: str,
    sandbox: str,
    status: str,
    launch_started_at: str,
) -> dict[str, object]:
    return {
        "status": status,
        "path": "agent-assignment.preview.json",
        "runtime": "codex-app-server",
        "model": model,
        "sandbox": sandbox,
        "launch_started_at": launch_started_at,
        "thread_id": task.thread_id,
        "turn_id": task.turn_id,
        "project_id": task.project_id,
        "cwd": str(task.cwd) if task.cwd is not None else None,
        "launched_at": _now(),
        "instruction_sources": [str(path) for path in task.instruction_sources],
    }


def _launching_state(
    *,
    repository: Path,
    model: str,
    sandbox: str,
    launch_started_at: str,
) -> dict[str, object]:
    return {
        "status": "launching",
        "path": "agent-assignment.preview.json",
        "runtime": "codex-app-server",
        "model": model,
        "sandbox": sandbox,
        "launch_started_at": launch_started_at,
        "thread_id": None,
        "turn_id": None,
        "project_id": None,
        "cwd": str(repository),
        "instruction_sources": [],
    }


def _validate_launch_assignment(
    *,
    coding_run: dict[str, object],
    assignment: dict[str, object],
    repository: Path,
) -> None:
    repository_data = _require_mapping(coding_run.get("repository"), "repository")
    expected_branch = _require_string(repository_data, "branch")
    expected_revision = _require_string(repository_data, "revision")
    branch, revision, working_tree_clean = _repository_state(repository)
    if (
        branch != expected_branch
        or revision != expected_revision
        or not working_tree_clean
    ):
        raise click.ClickException(
            "Repository changed since coding run: "
            f"expected {expected_branch}@{expected_revision}."
        )
    try:
        registry_result = subprocess.run(
            [
                "git",
                "show",
                f"{expected_revision}:docs/workstreams/registry.json",
            ],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        registry: object = json.loads(registry_result.stdout)
        validate_agent_assignment(
            assignment=assignment,
            registry=registry,
            repository_root=repository,
            expected_branch=expected_branch,
            expected_revision=expected_revision,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        AssignmentValidationError,
    ) as error:
        raise click.ClickException(
            f"Cannot validate coding assignment: {error}"
        ) from error
    final_branch, final_revision, final_working_tree_clean = _repository_state(
        repository
    )
    if (
        final_branch != expected_branch
        or final_revision != expected_revision
        or not final_working_tree_clean
    ):
        raise click.ClickException(
            "Repository changed during coding launch validation."
        )


def _repository_state(repository: Path) -> tuple[str, str, bool]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise click.ClickException(
            f"Cannot inspect repository: {repository}"
        ) from error
    branch = ""
    revision = ""
    working_tree_clean = True
    for line in result.stdout.splitlines():
        if line.startswith("# branch.head "):
            branch = line.removeprefix("# branch.head ")
        elif line.startswith("# branch.oid "):
            revision = line.removeprefix("# branch.oid ")
        elif not line.startswith("# "):
            working_tree_clean = False
    if branch == "(detached)":
        branch = ""
    return branch, revision, working_tree_clean


def launch_with_codex_app(
    *,
    codex_binary: str,
    title: str,
    repository: Path,
    model: str,
    sandbox: str,
    prompt: str,
    on_thread_started: Callable[[CodexTask], None] | None = None,
    before_turn: Callable[[], None] | None = None,
) -> CodexTask:
    """Launch through the persistent Codex app-server daemon."""
    project_roots = _repository_project_roots(repository)
    try:
        process = _start_proxy([codex_binary, "app-server", "proxy"])
    except OSError as error:
        raise CodexLaunchRetryableError(
            f"Cannot start Codex app-server proxy: {error}"
        ) from error
    if process.stdin is None or process.stdout is None or process.stderr is None:
        _stop_proxy(process)
        raise CodexLaunchRetryableError(
            "Codex app-server proxy has unavailable streams."
        )
    connection = _start_readers(process)

    try:
        try:
            _rpc_request(
                connection,
                request_id=1,
                method="initialize",
                params={
                    "capabilities": {
                        "experimentalApi": True,
                    },
                    "clientInfo": {
                        "name": "edifice",
                        "title": "Edifice",
                        "version": "0.1.0",
                    },
                },
            )
            _write_message(connection, {"method": "initialized"})
            expected_project_id, thread_request_id = _resolve_project(
                connection,
                repository,
                project_roots,
            )
        except click.ClickException as error:
            raise CodexLaunchRetryableError(error.message) from error
        thread_result = _rpc_request(
            connection,
            request_id=thread_request_id,
            method="thread/start",
            params={
                "approvalPolicy": "on-request",
                "cwd": str(repository),
                "ephemeral": False,
                "model": model,
                "projectId": expected_project_id,
                "sandbox": sandbox,
            },
        )
        thread = _require_mapping(thread_result.get("thread"), "Codex thread")
        thread_id = _require_string(thread, "id")
        partial_task = CodexTask(
            thread_id=thread_id,
            turn_id=None,
            project_id=None,
            cwd=None,
            instruction_sources=(),
        )
        try:
            if on_thread_started is not None:
                on_thread_started(partial_task)
            project_id = _optional_string(thread.get("projectId"))
            cwd_value = _optional_string(thread.get("cwd"))
            cwd = Path(cwd_value) if cwd_value is not None else None
            instruction_sources = _path_tuple(
                thread_result.get("instructionSources"),
                "instructionSources",
            )
            partial_task = CodexTask(
                thread_id=thread_id,
                turn_id=None,
                project_id=project_id,
                cwd=cwd,
                instruction_sources=instruction_sources,
            )
            effective_model = _require_string(thread_result, "model")
            sandbox_data = _require_mapping(
                thread_result.get("sandbox"),
                "Codex sandbox",
            )
            effective_sandbox = _require_string(sandbox_data, "type")
            expected_sandbox = {
                "read-only": "readOnly",
                "workspace-write": "workspaceWrite",
            }[sandbox]
            if effective_model != model:
                raise click.ClickException(
                    "Codex effective model mismatch: "
                    f"expected {model}, got {effective_model}."
                )
            if effective_sandbox != expected_sandbox:
                raise click.ClickException(
                    "Codex effective sandbox mismatch: "
                    f"expected {expected_sandbox}, got {effective_sandbox}."
                )
            if project_id is None:
                raise click.ClickException(
                    "Codex did not assign the task to a project."
                )
            if project_id != expected_project_id:
                raise click.ClickException(
                    "Codex task project mismatch: "
                    f"expected {expected_project_id}, got {project_id}."
                )
            if cwd is None:
                raise click.ClickException("Codex did not return the task worktree.")
            _rpc_request(
                connection,
                request_id=thread_request_id + 1,
                method="thread/name/set",
                params={
                    "name": title,
                    "threadId": thread_id,
                },
            )
            if before_turn is not None:
                before_turn()
            turn_result = _rpc_request(
                connection,
                request_id=thread_request_id + 2,
                method="turn/start",
                params={
                    "input": [{"type": "text", "text": prompt}],
                    "threadId": thread_id,
                },
            )
            turn = _require_mapping(turn_result.get("turn"), "Codex turn")
            turn_id = _require_string(turn, "id")
        except click.ClickException as error:
            raise CodexTaskStartedError(error.message, partial_task) from error
        return CodexTask(
            thread_id=thread_id,
            turn_id=turn_id,
            project_id=project_id,
            cwd=cwd,
            instruction_sources=instruction_sources,
        )
    finally:
        _stop_proxy(process)


def _start_proxy(arguments: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        arguments,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _resolve_project(
    connection: _AppServerConnection,
    repository: Path,
    candidate_roots: set[Path],
) -> tuple[str, int]:
    request_id = 2
    cursor: str | None = None
    matching_projects: set[str] = set()
    while True:
        params: dict[str, object] = {"limit": 100}
        if cursor is not None:
            params["cursor"] = cursor
        result = _rpc_request(
            connection,
            request_id=request_id,
            method="project/list",
            params=params,
        )
        projects_value = result.get("data")
        if not isinstance(projects_value, list):
            raise click.ClickException("Codex project list is invalid.")
        for value in cast(list[object], projects_value):
            project = _require_mapping(value, "Codex project")
            project_id = _require_string(project, "id")
            roots_value = project.get("roots")
            if not isinstance(roots_value, list):
                raise click.ClickException("Codex project roots must be a list.")
            root_paths = {
                Path(
                    _require_string(
                        _require_mapping(root, "Codex project root"),
                        "path",
                    )
                )
                .expanduser()
                .resolve()
                for root in cast(list[object], roots_value)
            }
            if root_paths.intersection(candidate_roots):
                matching_projects.add(project_id)
        cursor = _optional_string(result.get("nextCursor"))
        request_id += 1
        if cursor is None:
            break
    if not matching_projects:
        raise click.ClickException(
            f"No Codex project contains repository: {repository}"
        )
    if len(matching_projects) > 1:
        raise click.ClickException(
            f"Multiple Codex projects contain repository: {repository}"
        )
    return next(iter(matching_projects)), request_id


def _repository_project_roots(repository: Path) -> set[Path]:
    roots = {repository.expanduser().resolve()}
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return roots
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            roots.add(Path(line.removeprefix("worktree ")).resolve())
    return roots


def _rpc_request(
    connection: _AppServerConnection,
    *,
    request_id: int,
    method: str,
    params: dict[str, object],
) -> dict[str, object]:
    _write_message(
        connection,
        {
            "id": request_id,
            "method": method,
            "params": params,
        },
    )
    deadline = monotonic() + RPC_TIMEOUT_SECONDS
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise click.ClickException(f"Codex app-server timed out during {method}.")
        try:
            line = connection.responses.get(timeout=remaining)
        except Empty as error:
            raise click.ClickException(
                f"Codex app-server timed out during {method}."
            ) from error
        if line is None:
            error_output = " ".join(connection.stderr_lines).strip()
            detail = f": {error_output}" if error_output else ""
            raise click.ClickException(
                f"Codex app-server proxy closed during {method}{detail}"
            )
        try:
            response: object = json.loads(line)
        except json.JSONDecodeError as error:
            raise click.ClickException(
                f"Codex app-server returned invalid JSON during {method}."
            ) from error
        message = _require_mapping(response, "Codex app-server response")
        if message.get("id") != request_id:
            continue
        if "error" in message:
            raise click.ClickException(
                f"Codex app-server rejected {method}: {message['error']}"
            )
        return _require_mapping(message.get("result"), f"{method} result")


def _write_message(
    connection: _AppServerConnection,
    message: dict[str, object],
) -> None:
    assert connection.process.stdin is not None
    try:
        connection.process.stdin.write(
            json.dumps(message, separators=(",", ":")) + "\n"
        )
        connection.process.stdin.flush()
    except OSError as error:
        raise click.ClickException(
            f"Cannot write to Codex app-server proxy: {error}"
        ) from error


def _start_readers(process: subprocess.Popen[str]) -> _AppServerConnection:
    assert process.stdout is not None
    assert process.stderr is not None
    responses: Queue[str | None] = Queue()
    stderr_lines: list[str] = []
    Thread(
        target=_read_stdout,
        args=(process.stdout, responses),
        daemon=True,
    ).start()
    Thread(
        target=_read_stderr,
        args=(process.stderr, stderr_lines),
        daemon=True,
    ).start()
    return _AppServerConnection(
        process=process,
        responses=responses,
        stderr_lines=stderr_lines,
    )


def _read_stdout(stream: TextIO, responses: Queue[str | None]) -> None:
    try:
        while line := stream.readline():
            responses.put(line)
    except (OSError, ValueError):
        pass
    finally:
        responses.put(None)


def _read_stderr(stream: TextIO, stderr_lines: list[str]) -> None:
    try:
        while line := stream.readline():
            stderr_lines.append(line.strip())
    except (OSError, ValueError):
        pass


def _stop_proxy(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=5)
    except OSError:
        return
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _path_tuple(value: object, field: str) -> tuple[Path, ...]:
    if not isinstance(value, list):
        raise click.ClickException(f"Codex task field must be a list: {field}")
    paths: list[Path] = []
    for item in cast(list[object], value):
        if not isinstance(item, str) or not item:
            raise click.ClickException(f"Codex task list must contain paths: {field}")
        paths.append(Path(item))
    return tuple(paths)


def _launch_prompt(assignment: dict[str, object]) -> str:
    encoded_assignment = json.dumps(assignment, indent=2, sort_keys=True)
    return f"""Start this governed coding task.

Treat the assignment below as the durable authority for objective, mode,
learning level, context, writable paths, checks, prohibited effects, and
completion criteria. Do not widen it from conversation history.

At startup, report the assignment ID, workstream, exact revision, mode,
learning level, writable paths, prohibited effects, focused baseline result,
and any contradiction in the supplied context.

```json
{encoded_assignment}
```
"""


def _validate_task(task: CodexTask, repository: Path) -> tuple[str, str]:
    if not task.thread_id.strip():
        raise click.ClickException("Codex returned an empty thread ID.")
    if task.turn_id is None or not task.turn_id.strip():
        raise click.ClickException("Codex returned an empty turn ID.")
    if task.project_id is None or not task.project_id.strip():
        raise click.ClickException("Codex did not assign the task to a project.")
    if task.cwd is None:
        raise click.ClickException("Codex did not return the task worktree.")
    if task.cwd.resolve() != repository.resolve():
        raise click.ClickException(
            f"Codex task worktree mismatch: expected {repository}, got {task.cwd}"
        )
    return task.thread_id, task.project_id


def _load_mapping(path: Path, label: str) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {label}: {path}") from error
    return _require_mapping(value, label)


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise click.ClickException(f"{label.capitalize()} must be a JSON object.")
    return cast(dict[str, object], value)


def _require_string(mapping: dict[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise click.ClickException(f"Coding run field must be text: {field}")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise click.ClickException("Codex task field must be non-empty text.")
    return value


def _replace_json_atomically(path: Path, value: dict[str, object]) -> None:
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        temporary_path.chmod(path.stat().st_mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now().astimezone().isoformat()


@contextmanager
def _launch_lock(audit_root: Path) -> Generator[None]:
    audit_root.mkdir(parents=True, exist_ok=True)
    lock_path = audit_root / "code-launch.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
