import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from edifice.cli import cli


def _create_repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "--quiet", str(path)], check=True)
    return path


def _worker_response(
    repository: Path,
    *,
    summary: str = "Initial summary.",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "Build context gathering",
        "jira": {
            "key": "ABC-123",
            "title": "Build context gathering",
            "status": "In Progress",
            "url": "https://netflix.atlassian.net/browse/ABC-123",
            "summary": summary,
            "evidence_status": "verified",
        },
        "repository": {
            "path": str(repository),
            "revision": "abc123",
            "branch": "main",
            "working_tree": "clean",
            "summary": "Python CLI with Click.",
            "evidence_status": "verified",
        },
        "facts": [
            {
                "text": "The CLI entry point is edifice.cli:cli.",
                "source": "pyproject.toml",
                "evidence_status": "verified",
            }
        ],
        "sources": [
            {
                "label": "JIRA issue",
                "url": "https://netflix.atlassian.net/browse/ABC-123",
                "kind": "jira",
                "evidence_status": "verified",
            }
        ],
        "relevant_files": [
            {
                "path": "src/edifice/cli.py",
                "reason": "Defines the public CLI.",
                "evidence_status": "verified",
            }
        ],
        "blockers": [],
        "questions": ["Which repository interface should own refresh behavior?"],
        "next_actions": ["Implement one test-first vertical slice."],
    }


def _create_fake_codex(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "fake-codex"
    invocation_log = tmp_path / "codex-invocations.jsonl"
    executable.write_text(
        f"""#!{sys.executable}
import json
import os
import pathlib
import sys

arguments = sys.argv[1:]
with pathlib.Path(os.environ["EDIFICE_FAKE_CODEX_LOG"]).open("a") as log:
    log.write(json.dumps(arguments) + "\\n")

if arguments == ["mcp", "list", "--json"]:
    print(json.dumps([
        {{"name": "core-tools", "enabled": True}},
        {{"name": "jira-tools", "enabled": True}},
        {{"name": "github", "enabled": True}},
    ]))
    raise SystemExit(0)

output_path = pathlib.Path(arguments[arguments.index("-o") + 1])
output_path.write_text(os.environ["EDIFICE_FAKE_CODEX_RESPONSE"])
print(json.dumps({{"type": "turn.completed"}}))
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, invocation_log


def _invoke_gather(
    *,
    vault_root: Path,
    audit_root: Path,
    repository: Path,
    fake_codex: Path,
    invocation_log: Path,
    response: dict[str, object] | str,
    extra_arguments: list[str] | None = None,
):
    encoded_response = response if isinstance(response, str) else json.dumps(response)
    return CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(audit_root),
            "context",
            "gather",
            "--jira",
            "ABC-123",
            "--repo",
            str(repository),
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-22",
            *(extra_arguments or []),
        ],
        env={
            "EDIFICE_CODEX_BIN": str(fake_codex),
            "EDIFICE_FAKE_CODEX_LOG": str(invocation_log),
            "EDIFICE_FAKE_CODEX_RESPONSE": encoded_response,
        },
    )


def test_context_gather_creates_refreshable_note_with_manual_sections(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    fake_codex, invocation_log = _create_fake_codex(tmp_path)

    result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
    )

    note_path = (
        vault_root / "20-work" / "operations" / "projects" / "abc-123-context.md"
    )
    note = note_path.read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert result.output.startswith("Created 20-work/operations/projects/")
    assert "<!-- edifice:generated-context:start -->" in note
    assert "<!-- edifice:generated-context:end -->" in note
    assert "## Manual context" in note
    assert "### Notes" in note
    assert "Initial summary." in note


def test_context_refresh_preserves_manual_content_and_replaces_generated_content(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    first_result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
    )
    assert first_result.exit_code == 0
    note_path = (
        vault_root / "20-work" / "operations" / "projects" / "abc-123-context.md"
    )
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace(
            "### Notes\n\n",
            "### Notes\n\nMy manual context stays here.\n\n",
        ),
        encoding="utf-8",
    )

    second_result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository, summary="Refreshed summary."),
    )

    refreshed_note = note_path.read_text(encoding="utf-8")
    assert second_result.exit_code == 0
    assert second_result.output.startswith("Refreshed 20-work/operations/projects/")
    assert "My manual context stays here." in refreshed_note
    assert "Refreshed summary." in refreshed_note
    assert "Initial summary." not in refreshed_note


def test_context_gather_preserves_manual_links_and_pdf_references(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    first_result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
        extra_arguments=[
            "--link",
            "https://docs.google.com/document/d/example",
            "--pdf",
            "https://example.netflix.net/design.pdf",
        ],
    )
    assert first_result.exit_code == 0

    second_result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository, summary="Refreshed summary."),
    )

    note_path = (
        vault_root / "20-work" / "operations" / "projects" / "abc-123-context.md"
    )
    note = note_path.read_text(encoding="utf-8")
    assert second_result.exit_code == 0
    assert "https://docs.google.com/document/d/example" in note
    assert "https://example.netflix.net/design.pdf" in note


def test_context_gather_copies_explicit_pdf_without_overwriting_existing_bytes(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    source_pdf = tmp_path / "Design Notes V1.pdf"
    source_pdf.write_bytes(b"%PDF-1.7\napproved test bytes\n")
    fake_codex, invocation_log = _create_fake_codex(tmp_path)

    result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
        extra_arguments=[
            "--accept-pdf-name",
            "--copy-pdf",
            str(source_pdf),
            "https://example.netflix.net/design-notes-v1.pdf",
        ],
    )

    copied_pdf = (
        vault_root / "20-work" / "references" / "pdfs" / "inbox" / "design-notes-v1.pdf"
    )
    note_path = (
        vault_root / "20-work" / "operations" / "projects" / "abc-123-context.md"
    )
    expected_hash = f"sha256:{hashlib.sha256(source_pdf.read_bytes()).hexdigest()}"
    assert result.exit_code == 0
    assert copied_pdf.read_bytes() == source_pdf.read_bytes()
    assert (vault_root / "20-work" / "references" / "pdf-catalog.json").is_file()
    note = note_path.read_text(encoding="utf-8")
    assert expected_hash in note
    assert "hash-match" in note
    assert "https://example.netflix.net/design-notes-v1.pdf" in note

    copied_pdf.write_bytes(b"%PDF-1.7\ndifferent existing bytes\n")
    retry = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
        extra_arguments=[
            "--accept-pdf-name",
            "--copy-pdf",
            str(source_pdf),
            "https://example.netflix.net/design-notes-v1.pdf",
        ],
    )
    assert retry.exit_code != 0
    assert "Refusing to overwrite a different PDF" in retry.output
    assert copied_pdf.read_bytes() == b"%PDF-1.7\ndifferent existing bytes\n"


def test_context_gather_limits_codex_to_read_only_knowledge_search(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    fake_codex, invocation_log = _create_fake_codex(tmp_path)

    result = _invoke_gather(
        vault_root=tmp_path / "vault",
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
    )

    assert result.exit_code == 0
    invocations = [
        json.loads(line)
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
    ]
    assert invocations[0] == ["mcp", "list", "--json"]
    worker_arguments = invocations[1]
    assert "-a" in worker_arguments
    assert worker_arguments[worker_arguments.index("-a") + 1] == "never"
    assert "exec" in worker_arguments
    assert "-s" in worker_arguments
    assert worker_arguments[worker_arguments.index("-s") + 1] == "read-only"
    assert "--ephemeral" in worker_arguments
    assert "--output-schema" in worker_arguments
    assert "--json" in worker_arguments
    assert worker_arguments[worker_arguments.index("-C") + 1] == str(repository)
    assert 'mcp_servers.core-tools.enabled_tools=["nusdgs_search_knowledge_base"]' in (
        worker_arguments
    )
    assert "mcp_servers.jira-tools.enabled=false" in worker_arguments
    assert "mcp_servers.github.enabled=false" in worker_arguments


def test_context_gather_rejects_invalid_worker_output_without_writing_note(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    fake_codex, invocation_log = _create_fake_codex(tmp_path)

    result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response='{"schema_version": 1, "title": "Incomplete"}',
    )

    assert result.exit_code != 0
    assert "Codex returned invalid context data" in result.output
    assert not (
        vault_root / "20-work" / "operations" / "projects" / "abc-123-context.md"
    ).exists()


def test_context_gather_rejects_worker_link_to_wrong_jira_host(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    response = _worker_response(repository)
    jira = response["jira"]
    assert isinstance(jira, dict)
    jira["url"] = "https://attacker.example/browse/ABC-123"

    result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=response,
    )

    assert result.exit_code != 0
    assert "JIRA URL mismatch" in result.output
    assert not (
        vault_root / "20-work" / "operations" / "projects" / "abc-123-context.md"
    ).exists()


def test_context_refresh_requires_manual_metadata_change_before_new_values(
    tmp_path: Path,
) -> None:
    repository = _create_repository(tmp_path / "repo")
    vault_root = tmp_path / "vault"
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    first_result = _invoke_gather(
        vault_root=vault_root,
        audit_root=tmp_path / "audit",
        repository=repository,
        fake_codex=fake_codex,
        invocation_log=invocation_log,
        response=_worker_response(repository),
    )
    assert first_result.exit_code == 0

    changed_review_date = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(vault_root),
            "--audit-root",
            str(tmp_path / "audit"),
            "context",
            "gather",
            "--jira",
            "ABC-123",
            "--repo",
            str(repository),
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-10-01",
        ],
        env={
            "EDIFICE_CODEX_BIN": str(fake_codex),
            "EDIFICE_FAKE_CODEX_LOG": str(invocation_log),
            "EDIFICE_FAKE_CODEX_RESPONSE": json.dumps(_worker_response(repository)),
        },
    )

    assert changed_review_date.exit_code != 0
    assert "Edit the note metadata manually" in changed_review_date.output


def test_context_gather_rejects_relative_repository_path(tmp_path: Path) -> None:
    repository = _create_repository(tmp_path / "repo")
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "--vault",
            str(tmp_path / "vault"),
            "--audit-root",
            str(tmp_path / "audit"),
            "context",
            "gather",
            "--jira",
            "ABC-123",
            "--repo",
            os.path.relpath(repository),
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-22",
        ],
        env={
            "EDIFICE_CODEX_BIN": str(fake_codex),
            "EDIFICE_FAKE_CODEX_LOG": str(invocation_log),
            "EDIFICE_FAKE_CODEX_RESPONSE": json.dumps(_worker_response(repository)),
        },
    )

    assert result.exit_code != 0
    assert "Repository path must be absolute" in result.output
    assert not invocation_log.exists()
