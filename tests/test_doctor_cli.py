import json
from pathlib import Path

from click.testing import CliRunner

from personal_os.cli import cli

REQUIRED_FILES = [
    "AGENTS.md",
    "home.md",
    "00-system/operating-manual.md",
    "00-system/soul.md",
    "00-system/schema.md",
    "00-system/workflows.md",
    "00-system/engineering/owner-practices.md",
    "01-inbox/inbox.md",
    ".obsidian/core-plugins.json",
]


def test_doctor_accepts_complete_minimum_vault(tmp_path: Path) -> None:
    vault_root = tmp_path / "personal-os"
    for relative_path in REQUIRED_FILES:
        path = vault_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == ".obsidian/core-plugins.json":
            path.write_text(json.dumps({"sync": False}), encoding="utf-8")
        else:
            path.write_text(f"# {path.stem}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "doctor",
        ],
    )

    assert result.exit_code == 0
    assert result.output == "Healthy: minimum vault structure is present.\n"


def test_doctor_rejects_enabled_obsidian_sync(tmp_path: Path) -> None:
    vault_root = tmp_path / "personal-os"
    for relative_path in REQUIRED_FILES:
        path = vault_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == ".obsidian/core-plugins.json":
            path.write_text(json.dumps({"sync": True}), encoding="utf-8")
        else:
            path.write_text(f"# {path.stem}\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "doctor",
        ],
    )

    assert result.exit_code != 0
    assert "Obsidian Sync must be disabled for Kernel v0." in result.output
