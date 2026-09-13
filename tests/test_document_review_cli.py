import json
import sys
from pathlib import Path

from click.testing import CliRunner

from edifice.cli import cli


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


def _review_result(
    summary: str = "The documents agree on the core design.",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "review_name": "Architecture review",
        "documents": [
            {
                "document_id": "document-1",
                "source_url": "https://docs.google.com/document/d/one",
                "title": "First design",
                "evidence_status": "verified",
                "purpose": "Describe the proposed design.",
                "summary": "The first document proposes the main architecture.",
                "key_claims": [
                    {
                        "text": "The system should remain read-only.",
                        "evidence_status": "verified",
                    }
                ],
                "strengths": ["Clear ownership boundaries."],
                "concerns": ["Failure handling is underspecified."],
                "questions": ["Who owns recovery testing?"],
                "proposed_feedback": ["Define the recovery owner."],
            },
            {
                "document_id": "document-2",
                "source_url": "https://docs.google.com/document/d/two",
                "title": "Second design",
                "evidence_status": "verified",
                "purpose": "Describe the rollout.",
                "summary": "The second document proposes a staged rollout.",
                "key_claims": [
                    {
                        "text": "Rollout should use controlled phases.",
                        "evidence_status": "verified",
                    }
                ],
                "strengths": ["The rollout has explicit gates."],
                "concerns": ["Success evidence is vague."],
                "questions": ["What ends the pilot?"],
                "proposed_feedback": ["Add measurable exit evidence."],
            },
        ],
        "cross_document": {
            "summary": summary,
            "agreements": ["Both require staged delivery."],
            "conflicts": ["Ownership is assigned differently."],
            "gaps": ["Neither defines the recovery test."],
            "decision_points": ["Choose one recovery owner."],
            "proposed_feedback": ["Align ownership before approval."],
        },
        "limitations": ["Comments and revision history were unavailable."],
    }


def _base_arguments(vault_root: Path, audit_root: Path) -> list[str]:
    return [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
    ]


def test_review_docs_start_creates_reusable_manifest_and_notes(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "review-docs",
            "start",
            "--name",
            "Architecture review",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )

    manifest = (
        vault_root
        / "20-work"
        / "references"
        / "document-reviews"
        / "architecture-review.json"
    )
    context_note = (
        vault_root
        / "20-work"
        / "operations"
        / "projects"
        / "architecture-review-document-review.md"
    )
    ai_note = vault_root / "20-work" / "ai" / "architecture-review-document-review.md"
    assert result.exit_code == 0
    assert manifest.is_file()
    assert context_note.is_file()
    assert ai_note.is_file()
    assert "## Manual context" in context_note.read_text(encoding="utf-8")
    assert "<!-- edifice:document-review-analysis:start -->" in ai_note.read_text(
        encoding="utf-8"
    )


def test_review_docs_add_preserves_manual_notes_and_deduplicates_links(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    runner = CliRunner()
    started = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "review-docs",
            "start",
            "--name",
            "Architecture review",
            "--classification",
            "netflix-internal",
            "--review-on",
            "2026-09-15",
        ],
    )
    assert started.exit_code == 0
    context_note = (
        vault_root
        / "20-work"
        / "operations"
        / "projects"
        / "architecture-review-document-review.md"
    )
    context_note.write_text(
        context_note.read_text(encoding="utf-8").replace(
            "### Notes\n\n",
            "### Notes\n\nMy review criterion stays here.\n\n",
        ),
        encoding="utf-8",
    )

    first = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "review-docs",
            "add",
            "architecture-review",
            "--link",
            "https://docs.google.com/document/d/one",
        ],
    )
    duplicate = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "review-docs",
            "add",
            "architecture-review",
            "--link",
            "https://docs.google.com/document/d/one",
        ],
    )

    manifest = json.loads(
        (
            vault_root
            / "20-work"
            / "references"
            / "document-reviews"
            / "architecture-review.json"
        ).read_text(encoding="utf-8")
    )
    assert first.exit_code == 0
    assert duplicate.exit_code == 0
    assert "Already present" in duplicate.output
    assert len(manifest["documents"]) == 1
    assert "My review criterion stays here." in context_note.read_text(encoding="utf-8")


def test_review_docs_add_accepts_markdown_google_doc_and_owner_context(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    source_url = "https://docs.google.com/document/d/one/edit?tab=t.0"

    added = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "add",
            "architecture-review",
            "--link",
            f"[{source_url}]({source_url})",
            "--title",
            "Agent eval architecture",
            "--context",
            "Primary design; review API boundaries and rollout risks.",
        ],
    )

    manifest = json.loads(
        (
            vault_root
            / "20-work"
            / "references"
            / "document-reviews"
            / "architecture-review.json"
        ).read_text(encoding="utf-8")
    )
    document = manifest["documents"][0]
    context_note = (
        vault_root
        / "20-work"
        / "operations"
        / "projects"
        / "architecture-review-document-review.md"
    ).read_text(encoding="utf-8")
    assert added.exit_code == 0
    assert document["source_url"] == source_url
    assert document["kind"] == "google-doc"
    assert document["title"] == "Agent eval architecture"
    assert (
        document["context"]
        == "Primary design; review API boundaries and rollout risks."
    )
    assert "[Agent eval architecture]" in context_note
    assert "Primary design; review API boundaries and rollout risks." in context_note


def test_review_docs_add_detects_pdf_link_from_generic_link(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )

    added = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "add",
            "architecture-review",
            "--link",
            "https://example.netflix.net/design.pdf",
        ],
    )

    manifest = json.loads(
        (
            vault_root
            / "20-work"
            / "references"
            / "document-reviews"
            / "architecture-review.json"
        ).read_text(encoding="utf-8")
    )
    assert added.exit_code == 0
    assert manifest["documents"][0]["kind"] == "pdf-link"


def test_review_docs_add_updates_owner_context_without_duplicating_source(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    source_url = "https://docs.google.com/document/d/one/edit"
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "add",
                "architecture-review",
                "--link",
                source_url,
            ],
        ).exit_code
        == 0
    )

    updated = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "add",
            "architecture-review",
            "--link",
            f"[Architecture source]({source_url})",
            "--context",
            "Review its failure handling.",
        ],
    )

    manifest = json.loads(
        (
            vault_root
            / "20-work"
            / "references"
            / "document-reviews"
            / "architecture-review.json"
        ).read_text(encoding="utf-8")
    )
    assert updated.exit_code == 0
    assert "Updated" in updated.output
    assert len(manifest["documents"]) == 1
    assert manifest["documents"][0]["title"] == "Architecture source"
    assert manifest["documents"][0]["context"] == "Review its failure handling."


def test_review_docs_add_copy_pdf_uses_work_pdf_catalog(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    source_pdf = tmp_path / "Design Notes.pdf"
    source_pdf.write_bytes(b"%PDF-1.7\nreview fixture\n%%EOF\n")

    added = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "add",
            "architecture-review",
            "--copy-pdf",
            str(source_pdf),
            "https://example.netflix.net/design-notes.pdf",
            "--accept-pdf-name",
        ],
    )

    manifest = json.loads(
        (
            vault_root
            / "20-work"
            / "references"
            / "document-reviews"
            / "architecture-review.json"
        ).read_text(encoding="utf-8")
    )
    document = manifest["documents"][0]
    assert added.exit_code == 0
    assert document["kind"] == "local-pdf"
    assert document["local_path"].startswith("20-work/references/pdfs/")
    assert (vault_root / document["local_path"]).is_file()
    assert (vault_root / "20-work" / "references" / "pdf-catalog.json").is_file()


def test_review_docs_duplicate_pdf_url_does_not_copy_another_pdf(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    source_url = "https://example.netflix.net/design-notes.pdf"
    first_pdf = tmp_path / "First.pdf"
    first_pdf.write_bytes(b"%PDF-1.7\nfirst fixture\n%%EOF\n")
    second_pdf = tmp_path / "Second.pdf"
    second_pdf.write_bytes(b"%PDF-1.7\nsecond fixture\n%%EOF\n")
    for source_pdf in (first_pdf, second_pdf):
        result = runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "add",
                "architecture-review",
                "--copy-pdf",
                str(source_pdf),
                source_url,
                "--accept-pdf-name",
            ],
        )
        assert result.exit_code == 0

    catalog = json.loads(
        (vault_root / "20-work" / "references" / "pdf-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(catalog["artifacts"]) == 1
    assert (
        len(list((vault_root / "20-work" / "references" / "pdfs").rglob("*.pdf"))) == 1
    )


def test_review_docs_gather_uses_read_only_allowlisted_worker_and_preserves_manual_ai_notes(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    for url in (
        "https://docs.google.com/document/d/one",
        "https://docs.google.com/document/d/two",
    ):
        assert (
            runner.invoke(
                cli,
                [
                    *_base_arguments(vault_root, audit_root),
                    "review-docs",
                    "add",
                    "architecture-review",
                    "--link",
                    url,
                ],
            ).exit_code
            == 0
        )
    ai_note = vault_root / "20-work" / "ai" / "architecture-review-document-review.md"
    ai_note.write_text(
        ai_note.read_text(encoding="utf-8").replace(
            "## Manual analyst notes\n\n",
            "## Manual analyst notes\n\nMy manual observation.\n\n",
        ),
        encoding="utf-8",
    )
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    environment = {
        "EDIFICE_CODEX_BIN": str(fake_codex),
        "EDIFICE_FAKE_CODEX_LOG": str(invocation_log),
        "EDIFICE_FAKE_CODEX_RESPONSE": json.dumps(_review_result()),
    }

    gathered = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "gather",
            "architecture-review",
        ],
        env=environment,
    )

    assert gathered.exit_code == 0
    ai_content = ai_note.read_text(encoding="utf-8")
    assert "My manual observation." in ai_content
    assert "Failure handling is underspecified." in ai_content
    context_content = (
        vault_root
        / "20-work"
        / "operations"
        / "projects"
        / "architecture-review-document-review.md"
    ).read_text(encoding="utf-8")
    assert "[First design]" in context_content
    assert "Describe the proposed design." in context_content
    assert "The first document proposes the main architecture." in context_content
    invocations = [
        json.loads(line)
        for line in invocation_log.read_text(encoding="utf-8").splitlines()
    ]
    worker_arguments = invocations[1]
    assert worker_arguments[worker_arguments.index("-s") + 1] == "read-only"
    assert "--ephemeral" in worker_arguments
    assert (
        'mcp_servers.core-tools.enabled_tools=["nusdgs_search_knowledge_base",'
        '"nusdgs_read_knowledge_base_content"]'
    ) in worker_arguments
    assert "mcp_servers.jira-tools.enabled=false" in worker_arguments
    assert "mcp_servers.github.enabled=false" in worker_arguments


def test_review_docs_refresh_replaces_generated_analysis_only(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    for url in (
        "https://docs.google.com/document/d/one",
        "https://docs.google.com/document/d/two",
    ):
        assert (
            runner.invoke(
                cli,
                [
                    *_base_arguments(vault_root, audit_root),
                    "review-docs",
                    "add",
                    "architecture-review",
                    "--link",
                    url,
                ],
            ).exit_code
            == 0
        )
    fake_codex, invocation_log = _create_fake_codex(tmp_path)
    environment = {
        "EDIFICE_CODEX_BIN": str(fake_codex),
        "EDIFICE_FAKE_CODEX_LOG": str(invocation_log),
        "EDIFICE_FAKE_CODEX_RESPONSE": json.dumps(_review_result("Initial synthesis.")),
    }
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "gather",
                "architecture-review",
            ],
            env=environment,
        ).exit_code
        == 0
    )
    environment["EDIFICE_FAKE_CODEX_RESPONSE"] = json.dumps(
        _review_result("Refreshed synthesis.")
    )

    refreshed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "gather",
            "architecture-review",
        ],
        env=environment,
    )

    ai_note = (
        vault_root / "20-work" / "ai" / "architecture-review-document-review.md"
    ).read_text(encoding="utf-8")
    assert refreshed.exit_code == 0
    assert "Refreshed synthesis." in ai_note
    assert "Initial synthesis." not in ai_note
    run_reports = list(
        (vault_root / "20-work" / "run-reports").glob(
            "*-architecture-review-document-review-*.md"
        )
    )
    assert len(run_reports) == 2


def test_review_docs_synthesize_updates_context_without_overwriting_manual_context(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    context_note = (
        vault_root
        / "20-work"
        / "operations"
        / "projects"
        / "architecture-review-document-review.md"
    )
    context_note.write_text(
        context_note.read_text(encoding="utf-8").replace(
            "### Feedback draft\n\n",
            "### Feedback draft\n\nKeep this exact draft.\n\n",
        ),
        encoding="utf-8",
    )
    latest_path = (
        vault_root
        / "20-work"
        / "references"
        / "document-reviews"
        / "architecture-review-latest.json"
    )
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(_review_result()), encoding="utf-8")

    synthesized = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "synthesize",
            "architecture-review",
        ],
    )

    content = context_note.read_text(encoding="utf-8")
    assert synthesized.exit_code == 0
    assert "The documents agree on the core design." in content
    assert "Keep this exact draft." in content


def test_review_docs_status_reports_persistent_session_state(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )

    status = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "status",
            "architecture-review",
        ],
    )

    assert status.exit_code == 0
    assert "Review: Architecture review" in status.output
    assert "Documents: 0" in status.output
    assert "Status: active" in status.output


def test_review_docs_loads_manifest_created_before_owner_context_fields(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    manifest_path = (
        vault_root
        / "20-work"
        / "references"
        / "document-reviews"
        / "architecture-review.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"] = [
        {
            "document_id": "document-1",
            "kind": "link",
            "source_url": "https://docs.google.com/document/d/one/edit",
            "local_path": None,
            "label": "edit",
            "evidence_status": "owner-attested",
        }
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    status = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "status",
            "architecture-review",
        ],
    )

    assert status.exit_code == 0
    assert "Documents: 1" in status.output
    repeated_add = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "add",
            "architecture-review",
            "--link",
            "https://docs.google.com/document/d/one/edit",
        ],
    )
    migrated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert repeated_add.exit_code == 0
    assert migrated["documents"][0]["kind"] == "google-doc"
    assert migrated["documents"][0]["label"] == "Google Doc"
    assert migrated["documents"][0]["title"] is None
    assert migrated["documents"][0]["context"] is None


def test_review_docs_rejects_unsafe_session_slug(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(tmp_path / "vault", tmp_path / "audit"),
            "review-docs",
            "status",
            "../outside",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid document-review slug" in result.output


def test_review_docs_rejects_local_pdf_path_outside_governed_library(
    tmp_path: Path,
) -> None:
    vault_root = tmp_path / "vault"
    audit_root = tmp_path / "audit"
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, audit_root),
                "review-docs",
                "start",
                "--name",
                "Architecture review",
                "--classification",
                "netflix-internal",
                "--review-on",
                "2026-09-15",
            ],
        ).exit_code
        == 0
    )
    manifest_path = (
        vault_root
        / "20-work"
        / "references"
        / "document-reviews"
        / "architecture-review.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["documents"] = [
        {
            "document_id": "document-1",
            "kind": "local-pdf",
            "source_url": "https://example.netflix.net/design.pdf",
            "local_path": "../../outside.pdf",
            "label": "design.pdf",
            "evidence_status": "owner-attested",
        }
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    status = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, audit_root),
            "review-docs",
            "status",
            "architecture-review",
        ],
    )

    assert status.exit_code != 0
    assert "Invalid local PDF path" in status.output
