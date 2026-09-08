import json
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner

from edifice.cli import cli


def _create_legacy_vault(path: Path) -> Path:
    (path / ".obsidian").mkdir(parents=True)
    (path / ".obsidian" / "app.json").write_text(
        '{"attachmentFolderPath":"attachments"}\n',
        encoding="utf-8",
    )
    (path / "Projects").mkdir()
    (path / "Projects" / "Build a system.md").write_text(
        "# Build a system\n\n- [ ] Define the next action\n",
        encoding="utf-8",
    )
    (path / "Notes").mkdir()
    (path / "Notes" / "Distributed systems.md").write_text(
        "# Distributed systems\n\nLinks to [[Build a system]].\n",
        encoding="utf-8",
    )
    (path / "attachments").mkdir()
    (path / "attachments" / "diagram.png").write_bytes(b"\x89PNG\r\nfixture")
    (path / "empty-folder").mkdir()
    return path


def _invoke(
    *,
    vault_root: Path,
    audit_root: Path,
    migrations_root: Path,
    arguments: list[str],
):
    return CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            *arguments,
        ],
        env={"EDIFICE_MIGRATIONS_ROOT": str(migrations_root)},
    )


def _package_path(migrations_root: Path) -> Path:
    packages = list((migrations_root / "obsidian-personal").glob("*"))
    assert len(packages) == 1
    return packages[0]


def test_migration_inventory_snapshots_complete_obsidian_fixture_without_mutation(
    tmp_path: Path,
) -> None:
    source_vault = _create_legacy_vault(tmp_path / "legacy")
    source_before = {
        path.relative_to(source_vault): path.read_bytes()
        for path in source_vault.rglob("*")
        if path.is_file()
    }
    vault_root = tmp_path / "edifice"
    migrations_root = tmp_path / "migrations"

    result = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "obsidian",
            "--path",
            str(source_vault),
        ],
    )

    package = _package_path(migrations_root)
    inventory = json.loads((package / "inventory.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert inventory["file_count"] == 4
    assert inventory["directory_count"] == 6
    assert (package / "raw" / ".obsidian" / "app.json").is_file()
    assert (package / "raw" / "attachments" / "diagram.png").read_bytes() == (
        b"\x89PNG\r\nfixture"
    )
    assert (package / "raw" / "empty-folder").is_dir()
    assert all(
        not (path.stat().st_mode & stat.S_IWUSR)
        for path in (package / "raw").rglob("*")
        if path.is_file()
    )
    assert source_before == {
        path.relative_to(source_vault): path.read_bytes()
        for path in source_vault.rglob("*")
        if path.is_file()
    }
    assert not list((vault_root / "10-personal" / "notes").rglob("*.md"))
    assert (
        vault_root / "10-personal" / "operations" / "migrations" / "home.md"
    ).is_file()


def test_migration_plan_creates_review_mappings_without_live_import(
    tmp_path: Path,
) -> None:
    source_vault = _create_legacy_vault(tmp_path / "legacy")
    vault_root = tmp_path / "edifice"
    migrations_root = tmp_path / "migrations"
    inventoried = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "obsidian",
            "--path",
            str(source_vault),
        ],
    )
    assert inventoried.exit_code == 0
    package = _package_path(migrations_root)

    result = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "plan", str(package)],
    )

    mapping = json.loads((package / "mapping.json").read_text(encoding="utf-8"))
    assert result.exit_code == 0
    assert mapping["markdown_count"] == 2
    by_source = {item["source_path"]: item for item in mapping["items"]}
    project = by_source["Projects/Build a system.md"]
    note = by_source["Notes/Distributed systems.md"]
    assert project["title"] == "Build a system"
    assert project["candidate_type"] == "project"
    assert project["task_count"] == 1
    assert project["decision"] == "review"
    assert note["candidate_type"] == "knowledge"
    assert note["wiki_link_count"] == 1
    assert not list((vault_root / "10-personal" / "notes").rglob("*.md"))


def test_migration_verify_detects_changed_raw_file(tmp_path: Path) -> None:
    source_vault = _create_legacy_vault(tmp_path / "legacy")
    migrations_root = tmp_path / "migrations"
    inventoried = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "obsidian",
            "--path",
            str(source_vault),
        ],
    )
    assert inventoried.exit_code == 0
    package = _package_path(migrations_root)
    healthy = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "verify", str(package)],
    )
    raw_note = package / "raw" / "Notes" / "Distributed systems.md"
    raw_note.chmod(0o600)
    raw_note.write_text("changed", encoding="utf-8")
    changed = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "verify", str(package)],
    )

    assert healthy.exit_code == 0
    assert "4 verified, 0 unavailable, 0 mismatched" in healthy.output
    assert changed.exit_code != 0
    assert "[mismatched] Notes/Distributed systems.md" in changed.output


def test_migration_inventory_rejects_symlinked_source_content(
    tmp_path: Path,
) -> None:
    source_vault = _create_legacy_vault(tmp_path / "legacy")
    (source_vault / "unsafe-link").symlink_to("/tmp")
    migrations_root = tmp_path / "migrations"

    result = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "obsidian",
            "--path",
            str(source_vault),
        ],
    )

    assert result.exit_code != 0
    assert "Symlinks are not supported" in result.output
    assert not list(migrations_root.rglob("manifest.json"))


def test_migration_status_lists_created_package(tmp_path: Path) -> None:
    source_vault = _create_legacy_vault(tmp_path / "legacy")
    migrations_root = tmp_path / "migrations"
    inventoried = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "obsidian",
            "--path",
            str(source_vault),
        ],
    )
    assert inventoried.exit_code == 0

    result = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "status"],
    )

    assert result.exit_code == 0
    assert "obsidian-personal" in result.output
    assert "inventory-complete" in result.output


@pytest.mark.parametrize(
    ("source_kind", "file_name"),
    [
        ("craft", "Export.textbundle/text.md"),
        ("coda", "Owned doc.txt"),
    ],
)
def test_migration_inventory_supports_craft_and_coda_export_directories(
    tmp_path: Path,
    source_kind: str,
    file_name: str,
) -> None:
    source = tmp_path / f"{source_kind}-export"
    source_file = source / file_name
    source_file.parent.mkdir(parents=True)
    source_file.write_text("# Exported note\n", encoding="utf-8")
    if source_kind == "coda":
        (source / "Owned table.csv").write_text("name,value\none,1\n", encoding="utf-8")
    migrations_root = tmp_path / "migrations"

    inventoried = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            source_kind,
            "--path",
            str(source),
        ],
    )

    packages = list((migrations_root / f"{source_kind}-personal").glob("*"))
    assert inventoried.exit_code == 0
    assert len(packages) == 1
    manifest = json.loads((packages[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_kind"] == source_kind


def test_coda_plan_treats_text_as_note_and_csv_as_table_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "coda-export"
    source.mkdir()
    (source / "Owned doc.txt").write_text(
        "Owned doc\n\nA durable idea.\n",
        encoding="utf-8",
    )
    (source / "Owned table.csv").write_text(
        "name,value\none,1\n",
        encoding="utf-8",
    )
    migrations_root = tmp_path / "migrations"
    inventoried = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "coda",
            "--path",
            str(source),
        ],
    )
    assert inventoried.exit_code == 0
    package = next((migrations_root / "coda-personal").glob("*"))

    planned = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "plan", str(package)],
    )

    mapping = json.loads((package / "mapping.json").read_text(encoding="utf-8"))
    by_source = {item["source_path"]: item for item in mapping["items"]}
    assert planned.exit_code == 0
    assert by_source["Owned doc.txt"]["candidate_type"] == "knowledge"
    assert by_source["Owned table.csv"]["candidate_type"] == "table-artifact"


def test_obsidian_plan_separates_work_sources_imports_and_configuration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "legacy"
    (source / "Netflix").mkdir(parents=True)
    (source / "Netflix" / "Work project.md").write_text(
        "# Work project\n",
        encoding="utf-8",
    )
    (source / "Netflix" / "work-diagram.png").write_bytes(b"\x89PNG\r\nwork")
    (source / "Readwise").mkdir()
    (source / "Readwise" / "Imported article.md").write_text(
        "# Imported article\n",
        encoding="utf-8",
    )
    (source / "Readwise" / "article-image.png").write_bytes(b"\x89PNG\r\nsource")
    (source / ".obsidian").mkdir()
    (source / ".obsidian" / "app.json").write_text("{}\n", encoding="utf-8")
    migrations_root = tmp_path / "migrations"
    inventoried = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "inventory",
            "--source",
            "obsidian",
            "--path",
            str(source),
        ],
    )
    assert inventoried.exit_code == 0
    package = next((migrations_root / "obsidian-personal").glob("*"))

    planned = _invoke(
        vault_root=tmp_path / "edifice",
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "plan", str(package)],
    )

    mapping = json.loads((package / "mapping.json").read_text(encoding="utf-8"))
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    by_source = {item["source_path"]: item for item in mapping["items"]}
    assert planned.exit_code == 0
    assert by_source["Netflix/Work project.md"]["candidate_type"] == "work-source"
    assert by_source["Netflix/Work project.md"]["proposed_target"] is None
    assert by_source["Netflix/work-diagram.png"]["candidate_type"] == "work-source"
    assert by_source["Netflix/work-diagram.png"]["proposed_target"] is None
    assert by_source["Readwise/Imported article.md"]["candidate_type"] == "source-note"
    assert (
        by_source["Readwise/article-image.png"]["candidate_type"] == "source-artifact"
    )
    assert by_source[".obsidian/app.json"]["candidate_type"] == "configuration"
    assert by_source[".obsidian/app.json"]["proposed_target"] is None
    assert manifest["contains_work_content_candidates"] is True
    assert manifest["cloud_storage_status"] == "policy-blocked"
