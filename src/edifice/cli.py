import fcntl
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import click

from edifice.identifiers import new_uuid7


@dataclass(frozen=True)
class RuntimePaths:
    vault_root: Path
    audit_root: Path
    dry_run: bool


REQUIRED_VAULT_FILES = (
    Path("AGENTS.md"),
    Path("home.md"),
    Path("00-system/operating-manual.md"),
    Path("00-system/soul.md"),
    Path("00-system/schema.md"),
    Path("00-system/workflows.md"),
    Path("00-system/current.json"),
    Path("00-system/engineering/owner-practices.md"),
    Path("01-inbox/inbox.md"),
    Path(".obsidian/core-plugins.json"),
)


@click.group()
@click.option(
    "--vault",
    "vault_root",
    envvar="EDIFICE_VAULT",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option(
    "--audit-root",
    envvar="EDIFICE_AUDIT_ROOT",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option("--dry-run", is_flag=True, help="Show effects without opening Obsidian.")
@click.pass_context
def cli(
    context: click.Context,
    vault_root: Path,
    audit_root: Path,
    dry_run: bool,
) -> None:
    """Operate the local Edifice system."""
    context.obj = RuntimePaths(
        vault_root=vault_root,
        audit_root=audit_root,
        dry_run=dry_run,
    )


@cli.command()
@click.argument("text")
@click.pass_obj
def capture(paths: RuntimePaths, text: str) -> None:
    """Preserve text in the canonical inbox."""
    audit_path = _audit_path(paths.audit_root)
    with _capture_lock(paths.audit_root):
        capture_id = f"capture-{new_uuid7()}"
        inbox_path = paths.vault_root / "01-inbox" / "inbox.md"
        before = inbox_path.read_bytes()
        after = before + f"- [ ] {text} ^{capture_id}\n".encode()
        before_hash = _sha256(before)
        after_hash = _sha256(after)

        _append_audit_event(
            audit_path,
            event_type="capture.prepared",
            capture_id=capture_id,
            before_hash=before_hash,
            after_hash=after_hash,
        )
        _replace_atomically(inbox_path, after)
        _append_audit_event(
            audit_path,
            event_type="capture.committed",
            capture_id=capture_id,
            before_hash=before_hash,
            after_hash=after_hash,
        )
    click.echo(f"Captured {capture_id}")


@cli.command()
@click.pass_obj
def doctor(paths: RuntimePaths) -> None:
    """Verify the minimum local vault structure."""
    missing = [
        str(relative_path)
        for relative_path in REQUIRED_VAULT_FILES
        if not (paths.vault_root / relative_path).is_file()
    ]
    if missing:
        joined = ", ".join(missing)
        raise click.ClickException(f"Missing required vault files: {joined}")

    core_plugins_path = paths.vault_root / ".obsidian" / "core-plugins.json"
    core_plugins = json.loads(core_plugins_path.read_text(encoding="utf-8"))
    if core_plugins.get("sync") is True:
        raise click.ClickException("Obsidian Sync must be disabled for Kernel v0.")

    click.echo("Healthy: minimum vault structure is present.")


@cli.command()
@click.pass_obj
def start(paths: RuntimePaths) -> None:
    """Open the Edifice home note."""
    _open_note(paths, Path("home.md"))


@cli.command()
@click.pass_obj
def work(paths: RuntimePaths) -> None:
    """Open the active project."""
    _open_note(paths, _current_pointer(paths, "work"))


@cli.command()
@click.option(
    "--date",
    "selected_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def today(paths: RuntimePaths, selected_date: datetime | None) -> None:
    """Open a daily review."""
    review_date = (
        selected_date.date()
        if selected_date is not None
        else datetime.now().astimezone().date()
    )
    relative_path = (
        Path("10-personal/operations/reviews/daily") / f"{review_date.isoformat()}.md"
    )
    _open_note(paths, relative_path)


@cli.command()
@click.option(
    "--date",
    "selected_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def review(paths: RuntimePaths, selected_date: datetime | None) -> None:
    """Open the weekly review for a date."""
    review_date = (
        selected_date.date()
        if selected_date is not None
        else datetime.now().astimezone().date()
    )
    week_start = review_date - timedelta(days=review_date.weekday())
    relative_path = (
        Path("10-personal/operations/reviews/weekly")
        / f"{week_start.isoformat()}-weekly.md"
    )
    _open_note(paths, relative_path)


@cli.command()
@click.option(
    "--date",
    "selected_date",
    type=click.DateTime(formats=["%Y-%m-%d"]),
)
@click.pass_obj
def status(paths: RuntimePaths, selected_date: datetime | None) -> None:
    """Show the current operating state."""
    status_date = (
        selected_date.date()
        if selected_date is not None
        else datetime.now().astimezone().date()
    )
    week_start = status_date - timedelta(days=status_date.weekday())
    inbox_path = paths.vault_root / "01-inbox" / "inbox.md"
    inbox_count = sum(
        line.startswith("- [ ] ")
        for line in inbox_path.read_text(encoding="utf-8").splitlines()
    )
    work_path = _current_pointer(paths, "work")
    question_path = _current_pointer(paths, "question")
    today_path = (
        Path("10-personal/operations/reviews/daily") / f"{status_date.isoformat()}.md"
    )
    review_path = (
        Path("10-personal/operations/reviews/weekly")
        / f"{week_start.isoformat()}-weekly.md"
    )

    click.echo(f"Vault: {paths.vault_root}")
    click.echo(f"Inbox: {inbox_count} unprocessed")
    click.echo(f"Work: {work_path}")
    click.echo(f"Question: {question_path}")
    click.echo(f"Today: {today_path}")
    click.echo(f"Review: {review_path}")
    click.echo(f"Git: {_git_state(paths.vault_root)}")


def _git_state(vault_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(vault_root), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return "unavailable"
    return "changes" if result.stdout.strip() else "clean"


def _current_pointer(paths: RuntimePaths, key: str) -> Path:
    current_path = paths.vault_root / "00-system" / "current.json"
    try:
        current: object = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise click.ClickException(f"Cannot read {current_path}") from error

    if not isinstance(current, dict):
        raise click.ClickException("Current-state pointer must be a JSON object.")

    typed_current = cast(dict[str, object], current)
    value = typed_current.get(key)
    if not isinstance(value, str) or not value:
        raise click.ClickException(f"Current-state pointer is missing: {key}")

    relative_path = Path(value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise click.ClickException(f"Unsafe current-state pointer: {value}")
    return relative_path


def _open_note(paths: RuntimePaths, relative_path: Path) -> None:
    target = paths.vault_root / relative_path
    if not target.is_file():
        raise click.ClickException(f"Vault note does not exist: {relative_path}")

    if paths.dry_run:
        click.echo(f"Would open {relative_path} in Obsidian.")
        return

    query = urlencode(
        {
            "vault": paths.vault_root.name,
            "file": relative_path.as_posix(),
        }
    )
    subprocess.run(["open", f"obsidian://open?{query}"], check=True)
    click.echo(f"Opened {relative_path} in Obsidian.")


def _sha256(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _audit_path(audit_root: Path) -> Path:
    audit_root.mkdir(parents=True, exist_ok=True)
    return audit_root / f"{datetime.now(UTC).date().isoformat()}.jsonl"


@contextmanager
def _capture_lock(audit_root: Path) -> Generator[None]:
    lock_path = audit_root / "capture.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _append_audit_event(
    audit_path: Path,
    *,
    event_type: str,
    capture_id: str,
    before_hash: str,
    after_hash: str,
) -> None:
    event = {
        "schema_version": 1,
        "event_id": f"event-{new_uuid7()}",
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": "personal",
        "event_type": event_type,
        "capture_id": capture_id,
        "target": "vault://edifice/01-inbox/inbox.md",
        "before_hash": before_hash,
        "after_hash": after_hash,
    }
    encoded = f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n".encode()
    descriptor = os.open(
        audit_path,
        os.O_APPEND | os.O_CREAT | os.O_WRONLY,
        0o600,
    )
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_atomically(target: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)

    try:
        temporary_path.chmod(target.stat().st_mode)
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
