import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import click

from personal_os.identifiers import new_uuid7


@dataclass(frozen=True)
class RuntimePaths:
    vault_root: Path
    audit_root: Path


REQUIRED_VAULT_FILES = (
    Path("AGENTS.md"),
    Path("home.md"),
    Path("00-system/operating-manual.md"),
    Path("00-system/soul.md"),
    Path("00-system/schema.md"),
    Path("00-system/workflows.md"),
    Path("00-system/engineering/owner-practices.md"),
    Path("01-inbox/inbox.md"),
    Path(".obsidian/core-plugins.json"),
)


@click.group()
@click.option(
    "--vault",
    "vault_root",
    envvar="PERSONAL_OS_VAULT",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.option(
    "--audit-root",
    envvar="PERSONAL_OS_AUDIT_ROOT",
    required=True,
    type=click.Path(path_type=Path, file_okay=False),
)
@click.pass_context
def cli(context: click.Context, vault_root: Path, audit_root: Path) -> None:
    """Operate the local Obsidian personal system."""
    context.obj = RuntimePaths(vault_root=vault_root, audit_root=audit_root)


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
        "target": "vault://personal/01-inbox/inbox.md",
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
