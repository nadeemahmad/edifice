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


def _create_essentials_vault(path: Path) -> Path:
    (path / "Essentials").mkdir(parents=True)
    (path / "Essentials" / "Goals.md").write_text(
        "# Goals\n\n- [ ] Build something useful\n",
        encoding="utf-8",
    )
    (path / "Essentials" / "Joe Vogel Notes.md").write_text(
        "# Joe Vogel Notes\n\nA durable note.\n",
        encoding="utf-8",
    )
    (path / "Essentials" / "Notes for BDAY.md").write_text(
        "# Notes for BDAY\n\nRemember this.\n",
        encoding="utf-8",
    )
    (path / "Other").mkdir()
    (path / "Other" / "Leave for later.md").write_text(
        "# Leave for later\n",
        encoding="utf-8",
    )
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
    assert by_source["Netflix/Work project.md"]["proposed_target"] == (
        "20-work/references/imported/work-project.md"
    )
    assert by_source["Netflix/work-diagram.png"]["candidate_type"] == "work-source"
    assert by_source["Netflix/work-diagram.png"]["proposed_target"] == (
        "20-work/references/imported/work-diagram.png"
    )
    assert by_source["Readwise/Imported article.md"]["candidate_type"] == "source-note"
    assert (
        by_source["Readwise/article-image.png"]["candidate_type"] == "source-artifact"
    )
    assert by_source[".obsidian/app.json"]["candidate_type"] == "configuration"
    assert by_source[".obsidian/app.json"]["proposed_target"] is None
    assert manifest["contains_work_content_candidates"] is True
    assert manifest["local_migration_status"] == "review-allowed"
    assert manifest["cloud_storage_status"] == "policy-blocked"


def test_migration_approve_binds_essentials_to_protected_note_targets(
    tmp_path: Path,
) -> None:
    source = _create_essentials_vault(tmp_path / "legacy")
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
            str(source),
        ],
    )
    assert inventoried.exit_code == 0
    package = next((migrations_root / "obsidian-personal").glob("*"))
    planned = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "plan", str(package)],
    )
    assert planned.exit_code == 0

    approved = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "approve",
            str(package),
            "--source-prefix",
            "Essentials/",
            "--route",
            "protected-note",
        ],
    )

    mapping = json.loads((package / "mapping.json").read_text(encoding="utf-8"))
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    essentials = [
        item
        for item in mapping["items"]
        if item["source_path"].startswith("Essentials/")
    ]
    deferred = [
        item for item in mapping["items"] if item["source_path"].startswith("Other/")
    ]
    assert approved.exit_code == 0
    assert "Approved: 3" in approved.output
    assert {item["decision"] for item in essentials} == {"approved"}
    assert {item["approved_target"] for item in essentials} == {
        "10-personal/notes/imported/goals.md",
        "10-personal/notes/imported/joe-vogel-notes.md",
        "10-personal/notes/imported/notes-for-bday.md",
    }
    assert {item["decision"] for item in deferred} == {"review"}
    assert manifest["status"] == "approved"
    assert manifest["approved_mapping_sha256"].startswith("sha256:")


def test_migration_apply_copies_exact_approved_notes_and_is_idempotent(
    tmp_path: Path,
) -> None:
    source = _create_essentials_vault(tmp_path / "legacy")
    source_before = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
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
            str(source),
        ],
    )
    assert inventoried.exit_code == 0
    package = next((migrations_root / "obsidian-personal").glob("*"))
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=["migrate", "plan", str(package)],
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=[
                "migrate",
                "approve",
                str(package),
                "--source-prefix",
                "Essentials/",
                "--route",
                "protected-note",
            ],
        ).exit_code
        == 0
    )

    applied = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "apply", str(package)],
    )
    applied_again = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "apply", str(package)],
    )

    for source_path in (
        "Goals.md",
        "Joe Vogel Notes.md",
        "Notes for BDAY.md",
    ):
        source_bytes = (source / "Essentials" / source_path).read_bytes()
        target_name = (
            source_path.removesuffix(".md").casefold().replace(" ", "-") + ".md"
        )
        target_bytes = (
            vault_root / "10-personal" / "notes" / "imported" / target_name
        ).read_bytes()
        assert target_bytes == source_bytes
    mapping = json.loads((package / "mapping.json").read_text(encoding="utf-8"))
    essentials = [
        item
        for item in mapping["items"]
        if item["source_path"].startswith("Essentials/")
    ]
    assert applied.exit_code == 0
    assert "Imported: 3; already imported: 0" in applied.output
    assert applied_again.exit_code == 0
    assert "Imported: 0; already imported: 3" in applied_again.output
    assert {item["apply_status"] for item in essentials} == {"imported"}
    cockpit = (
        vault_root / "10-personal" / "operations" / "migrations" / "home.md"
    ).read_text(encoding="utf-8")
    assert "Status: `applied-partial`" in cockpit
    assert "edifice migrate approve" in cockpit
    assert "Imported notes are protected exact copies." in cockpit
    assert source_before == {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }


def test_migration_apply_preflights_conflicts_before_writing_any_target(
    tmp_path: Path,
) -> None:
    source = _create_essentials_vault(tmp_path / "legacy")
    vault_root = tmp_path / "edifice"
    migrations_root = tmp_path / "migrations"
    assert (
        _invoke(
            vault_root=vault_root,
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
        ).exit_code
        == 0
    )
    package = next((migrations_root / "obsidian-personal").glob("*"))
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=["migrate", "plan", str(package)],
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=[
                "migrate",
                "approve",
                str(package),
                "--source-prefix",
                "Essentials/",
                "--route",
                "protected-note",
            ],
        ).exit_code
        == 0
    )
    conflicting = vault_root / "10-personal" / "notes" / "imported" / "goals.md"
    conflicting.parent.mkdir(parents=True)
    conflicting.write_text("different", encoding="utf-8")

    applied = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "apply", str(package)],
    )

    assert applied.exit_code != 0
    assert "Refusing to overwrite a different migrated note" in applied.output
    assert not (
        vault_root / "10-personal" / "notes" / "imported" / "joe-vogel-notes.md"
    ).exists()
    assert conflicting.read_text(encoding="utf-8") == "different"


def test_migration_apply_rejects_mapping_changed_after_approval(
    tmp_path: Path,
) -> None:
    source = _create_essentials_vault(tmp_path / "legacy")
    vault_root = tmp_path / "edifice"
    migrations_root = tmp_path / "migrations"
    assert (
        _invoke(
            vault_root=vault_root,
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
        ).exit_code
        == 0
    )
    package = next((migrations_root / "obsidian-personal").glob("*"))
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=["migrate", "plan", str(package)],
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=[
                "migrate",
                "approve",
                str(package),
                "--source-prefix",
                "Essentials/",
                "--route",
                "protected-note",
            ],
        ).exit_code
        == 0
    )
    mapping_path = package / "mapping.json"
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping["items"][0]["title"] = "Changed after approval"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")

    applied = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "apply", str(package)],
    )

    assert applied.exit_code != 0
    assert "mapping changed after approval" in applied.output
    assert not list((vault_root / "10-personal" / "notes").rglob("*.md"))


def test_migration_supports_sequential_approved_batches(tmp_path: Path) -> None:
    source = _create_essentials_vault(tmp_path / "legacy")
    (source / "Writing").mkdir()
    (source / "Writing" / "Essay.md").write_text(
        "# Essay\n\nAn exact writing draft.\n",
        encoding="utf-8",
    )
    vault_root = tmp_path / "edifice"
    migrations_root = tmp_path / "migrations"
    assert (
        _invoke(
            vault_root=vault_root,
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
        ).exit_code
        == 0
    )
    package = next((migrations_root / "obsidian-personal").glob("*"))
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=["migrate", "plan", str(package)],
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=[
                "migrate",
                "approve",
                str(package),
                "--source-prefix",
                "Essentials/",
                "--route",
                "protected-note",
            ],
        ).exit_code
        == 0
    )
    assert (
        _invoke(
            vault_root=vault_root,
            audit_root=tmp_path / "audit",
            migrations_root=migrations_root,
            arguments=["migrate", "apply", str(package)],
        ).exit_code
        == 0
    )

    approved_writing = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=[
            "migrate",
            "approve",
            str(package),
            "--source-prefix",
            "Writing/",
            "--route",
            "protected-note",
        ],
    )
    applied_writing = _invoke(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        migrations_root=migrations_root,
        arguments=["migrate", "apply", str(package)],
    )

    assert approved_writing.exit_code == 0
    assert "Approved: 1" in approved_writing.output
    assert applied_writing.exit_code == 0
    assert "Imported: 1; already imported: 3" in applied_writing.output
    assert (vault_root / "10-personal" / "notes" / "imported" / "essay.md").read_text(
        encoding="utf-8"
    ) == "# Essay\n\nAn exact writing draft.\n"
