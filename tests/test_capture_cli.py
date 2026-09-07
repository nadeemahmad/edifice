import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from edifice.cli import cli


def test_capture_preserves_text_in_canonical_inbox(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text("# Inbox\n\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "capture",
            "Remember this exact wording.",
        ],
    )

    assert result.exit_code == 0
    assert "- [ ] Remember this exact wording. ^capture-" in inbox_path.read_text(
        encoding="utf-8"
    )
    assert result.output.startswith("Captured capture-")


def test_capture_records_audit_evidence_without_captured_text(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text("# Inbox\n\n", encoding="utf-8")
    audit_root = tmp_path / "audit"

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "capture",
            "Private words stay out of audit.",
        ],
    )

    assert result.exit_code == 0
    audit_files = list(audit_root.glob("*.jsonl"))
    assert len(audit_files) == 1
    events = [
        json.loads(line)
        for line in audit_files[0].read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event_type"] for event in events] == [
        "capture.prepared",
        "capture.committed",
    ]
    assert events[0]["capture_id"] == events[1]["capture_id"]
    assert events[0]["before_hash"] != events[0]["after_hash"]
    assert "Private words stay out of audit." not in audit_files[0].read_text(
        encoding="utf-8"
    )


def test_concurrent_captures_are_all_preserved(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(f"# Inbox\n\n<!-- {'x' * 200_000} -->\n", encoding="utf-8")
    audit_root = tmp_path / "audit"
    executable = Path(__file__).parents[1] / "bin" / "edifice"

    processes = [
        subprocess.Popen(
            [
                str(executable),
                "--vault",
                str(vault_root),
                "--audit-root",
                str(audit_root),
                "capture",
                f"Concurrent capture {index}.",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for index in range(12)
    ]

    for process in processes:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, f"{stdout}\n{stderr}"

    inbox = inbox_path.read_text(encoding="utf-8")
    for index in range(12):
        assert inbox.count(f"Concurrent capture {index}.") == 1
