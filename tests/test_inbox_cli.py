import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner
from pytest import MonkeyPatch

from edifice.cli import cli


def _base_arguments(vault_root: Path, audit_root: Path) -> list[str]:
    return [
        "--vault",
        str(vault_root),
        "--audit-root",
        str(audit_root),
    ]


def test_inbox_process_identifies_freeform_capture_and_creates_review(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Think about evaluation report structure.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 8, 16, 0, tzinfo=UTC),
    )

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )

    inbox = inbox_path.read_text(encoding="utf-8")
    capture_match = re.search(r"\^(capture-[0-9a-f-]{36})", inbox)
    assert capture_match is not None
    capture_id = capture_match.group(1)
    routing_path = vault_root / "10-personal" / "operations" / "inbox" / "routing.json"
    review_path = vault_root / "10-personal" / "operations" / "inbox" / "review.md"
    routing = json.loads(routing_path.read_text(encoding="utf-8"))
    capture = routing["captures"][capture_id]
    review = review_path.read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert result.output == (
        "Processed captures: 1.\n"
        "Needs review: 1.\n"
        "Routing failures: 0.\n"
        "Review: 10-personal/operations/inbox/review.md.\n"
    )
    assert capture["source_hash"].startswith("sha256:")
    assert capture["status"] == "needs-review"
    assert capture["suggested_route"] == "review"
    assert capture["evidence_status"] == "unavailable"
    assert capture_id in review
    assert "Think about evaluation report structure." in review
    assert "No route was inferred." in review

    processed_again = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )

    assert processed_again.exit_code == 0
    assert inbox_path.read_text(encoding="utf-8").count(capture_id) == 1


def test_inbox_review_processes_and_opens_review_note(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Review this capture later.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
    )

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "--dry-run",
            "inbox",
            "review",
        ],
    )

    review_path = Path("10-personal/operations/inbox/review.md")
    assert result.exit_code == 0
    assert result.output == (
        "Processed captures: 1.\n"
        "Needs review: 1.\n"
        "Routing failures: 0.\n"
        f"Review: {review_path}.\n"
        f"Would open {review_path} in Obsidian.\n"
    )
    assert (vault_root / review_path).is_file()


def test_inbox_route_moves_capture_to_current_work_note_idempotently(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Think about evaluation report structure.\n",
        encoding="utf-8",
    )
    work_relative_path = Path("20-work/operations/projects/evaluation-work.md")
    work_path = vault_root / work_relative_path
    work_path.parent.mkdir(parents=True)
    work_path.write_text(
        """# Evaluation work

## Manual context

### Notes

### Links

### PDFs

### Decisions

### Questions

## Tasks
""",
        encoding="utf-8",
    )
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps({"work": work_relative_path.as_posix()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 8, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    processed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )
    assert processed.exit_code == 0
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)

    first = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "current-work-note",
        ],
    )
    second = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "current-work-note",
        ],
    )

    inbox = inbox_path.read_text(encoding="utf-8")
    work_note = work_path.read_text(encoding="utf-8")
    routing = json.loads(
        (
            vault_root / "10-personal" / "operations" / "inbox" / "routing.json"
        ).read_text(encoding="utf-8")
    )
    record = routing["captures"][capture_id]
    assert first.exit_code == 0
    assert first.output == (f"Routed {capture_id} to {work_relative_path}#notes.\n")
    assert second.exit_code == 0
    assert second.output == (
        f"Already routed {capture_id} to {work_relative_path}#notes.\n"
    )
    assert f"- [x] Think about evaluation report structure. ^{capture_id}" in inbox
    assert "Think about evaluation report structure." in work_note
    assert f"[[01-inbox/inbox#^{capture_id}|capture]]" in work_note
    assert work_note.count("Think about evaluation report structure.") == 1
    assert record["status"] == "routed"
    assert record["destination"] == f"{work_relative_path}#notes"
    assert record["route_id"].startswith("route-")
    audit_path = tmp_path / "audit" / "2026-09-08.jsonl"
    audit = audit_path.read_text(encoding="utf-8")
    assert '"event_type":"capture.routed"' in audit
    assert capture_id in audit
    assert "Think about evaluation report structure." not in audit


def test_inbox_process_suggests_and_routes_explicit_personal_idea(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] personal idea: Write about bounded automation.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 8, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()

    processed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )

    inbox = inbox_path.read_text(encoding="utf-8")
    capture_match = re.search(r"\^(capture-[0-9a-f-]{36})", inbox)
    assert processed.exit_code == 0
    assert capture_match is not None
    capture_id = capture_match.group(1)
    review_path = vault_root / "10-personal" / "operations" / "inbox" / "review.md"
    review = review_path.read_text(encoding="utf-8")
    assert "Suggested route: `personal-idea`" in review
    assert "Evidence: `owner-attested`" in review

    routed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "personal-idea",
        ],
    )

    idea_path = vault_root / "10-personal" / "ai" / "ideas" / "capture-ideas.md"
    idea_note = idea_path.read_text(encoding="utf-8")
    assert routed.exit_code == 0
    assert routed.output == (
        f"Routed {capture_id} to 10-personal/ai/ideas/capture-ideas.md#captures.\n"
    )
    assert "personal idea: Write about bounded automation." in idea_note
    assert "not owner commitments" in idea_note
    assert (
        f"- [x] personal idea: Write about bounded automation. ^{capture_id}"
        in inbox_path.read_text(encoding="utf-8")
    )


def test_inbox_process_reports_missing_routed_destination(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Preserve this work note.\n",
        encoding="utf-8",
    )
    work_relative_path = Path("20-work/operations/projects/evaluation-work.md")
    work_path = vault_root / work_relative_path
    work_path.parent.mkdir(parents=True)
    work_path.write_text(
        "# Work\n\n## Manual context\n\n### Notes\n",
        encoding="utf-8",
    )
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps({"work": work_relative_path.as_posix()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 8, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "route",
                capture_id,
                "--to",
                "current-work-note",
            ],
        ).exit_code
        == 0
    )
    work_path.unlink()

    reconciled = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )

    review = (
        vault_root / "10-personal" / "operations" / "inbox" / "review.md"
    ).read_text(encoding="utf-8")
    assert reconciled.exit_code == 0
    assert "Routing failures: 1." in reconciled.output
    assert capture_id in review
    assert "Routed destination is unavailable." in review


def test_inbox_route_archives_capture_without_deleting_source(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] This was only a capture test.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)

    archived = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "archive",
        ],
    )
    archived_again = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "archive",
        ],
    )
    reconciled = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )

    inbox = inbox_path.read_text(encoding="utf-8")
    routing = json.loads(
        (
            vault_root / "10-personal" / "operations" / "inbox" / "routing.json"
        ).read_text(encoding="utf-8")
    )
    record = routing["captures"][capture_id]
    review = (
        vault_root / "10-personal" / "operations" / "inbox" / "review.md"
    ).read_text(encoding="utf-8")
    audit = (tmp_path / "audit" / "2026-09-09.jsonl").read_text(encoding="utf-8")
    assert archived.exit_code == 0
    assert archived.output == f"Archived {capture_id}.\n"
    assert archived_again.exit_code == 0
    assert archived_again.output == f"Already archived {capture_id}.\n"
    assert reconciled.exit_code == 0
    assert "Routing failures: 0." in reconciled.output
    assert f"- [x] This was only a capture test. ^{capture_id}" in inbox
    assert "Disposition: `archived`" in inbox
    assert record["status"] == "archived"
    assert record["destination"] is None
    assert "Archived: 1" in review
    assert "Needs review: 0" in review
    assert '"event_type":"capture.archived"' in audit
    assert "This was only a capture test." not in audit


def test_inbox_route_adds_note_to_selected_personal_project(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Remember why this project matters.\n",
        encoding="utf-8",
    )
    project_relative_path = Path("10-personal/operations/projects/first-deliverable.md")
    project_path = vault_root / project_relative_path
    project_path.parent.mkdir(parents=True)
    project_path.write_text(
        """# First deliverable

## Result

## Current state

## Resume point

## Tasks

## Questions
""",
        encoding="utf-8",
    )
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps({"work": project_relative_path.as_posix()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)

    routed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "personal-project-note",
        ],
    )

    project = project_path.read_text(encoding="utf-8")
    assert routed.exit_code == 0
    assert routed.output == (
        f"Routed {capture_id} to {project_relative_path}#current-state.\n"
    )
    assert "Remember why this project matters." in project
    assert f"[[01-inbox/inbox#^{capture_id}|capture]]" in project


def test_inbox_route_saves_classified_work_idea_without_creating_task(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] work idea: Adapt retries to the failure type.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    processed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "process",
        ],
    )
    assert processed.exit_code == 0
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)
    review = (
        vault_root / "10-personal" / "operations" / "inbox" / "review.md"
    ).read_text(encoding="utf-8")
    assert "Suggested route: `work-idea`" in review
    assert "Evidence: `owner-attested`" in review

    routed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "work-idea",
            "--classification",
            "netflix-internal",
        ],
    )

    idea_relative_path = Path("20-work/operations/ideas/seeds.md")
    idea_note = (vault_root / idea_relative_path).read_text(encoding="utf-8")
    assert routed.exit_code == 0
    assert routed.output == (f"Routed {capture_id} to {idea_relative_path}#seeds.\n")
    assert "work idea: Adapt retries to the failure type." in idea_note
    assert "Classification: `netflix-internal`" in idea_note
    assert "- [ ] work idea:" not in idea_note
    assert f"[[01-inbox/inbox#^{capture_id}|capture]]" in idea_note


def test_inbox_review_interactively_routes_personal_idea_and_archives(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        """# Inbox

- [ ] Write about bounded automation.
- [ ] This was only a test.
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
    )

    result = CliRunner().invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "--dry-run",
            "inbox",
            "review",
            "--interactive",
        ],
        input="personal\nidea\ny\narchive\ny\n",
    )

    routing = json.loads(
        (
            vault_root / "10-personal" / "operations" / "inbox" / "routing.json"
        ).read_text(encoding="utf-8")
    )
    statuses = sorted(capture["status"] for capture in routing["captures"].values())
    idea_note = (
        vault_root / "10-personal" / "ai" / "ideas" / "capture-ideas.md"
    ).read_text(encoding="utf-8")
    inbox = inbox_path.read_text(encoding="utf-8")
    assert result.exit_code == 0
    assert statuses == ["archived", "routed"]
    assert "Write about bounded automation." in idea_note
    assert "Disposition: `archived`" in inbox
    assert "Needs review: 0." in result.output
    assert "Would open 10-personal/operations/inbox/review.md in Obsidian." in (
        result.output
    )


def test_inbox_route_rejects_classification_for_personal_destination(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Preserve this as a personal idea.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)

    routed = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "personal-idea",
            "--classification",
            "netflix-confidential",
        ],
    )

    assert routed.exit_code != 0
    assert "Classification is allowed only for work-idea routes." in routed.output
    assert not (
        vault_root / "10-personal" / "ai" / "ideas" / "capture-ideas.md"
    ).exists()
    assert f"- [ ] Preserve this as a personal idea. ^{capture_id}" in (
        inbox_path.read_text(encoding="utf-8")
    )


def test_inbox_route_rejects_different_route_after_completion(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Keep this work note.\n",
        encoding="utf-8",
    )
    work_relative_path = Path("20-work/operations/projects/current-work.md")
    work_path = vault_root / work_relative_path
    work_path.parent.mkdir(parents=True)
    work_path.write_text(
        """# Current work

## Manual context

### Notes

### Questions

## Tasks
""",
        encoding="utf-8",
    )
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps({"work": work_relative_path.as_posix()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "route",
                capture_id,
                "--to",
                "current-work-note",
            ],
        ).exit_code
        == 0
    )
    routing_path = vault_root / "10-personal" / "operations" / "inbox" / "routing.json"
    routing_before = routing_path.read_bytes()
    inbox_before = inbox_path.read_bytes()

    rerouted = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "archive",
        ],
    )

    assert rerouted.exit_code != 0
    assert "Capture already completed through route current-work-note." in (
        rerouted.output
    )
    assert routing_path.read_bytes() == routing_before
    assert inbox_path.read_bytes() == inbox_before
    assert "Disposition: `archived`" not in inbox_path.read_text(encoding="utf-8")


def test_inbox_route_rejects_different_destination_after_interrupted_route(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] Keep this work note.\n",
        encoding="utf-8",
    )
    work_relative_path = Path("20-work/operations/projects/current-work.md")
    work_path = vault_root / work_relative_path
    work_path.parent.mkdir(parents=True)
    work_path.write_text(
        """# Current work

## Manual context

### Notes

### Questions

## Tasks
""",
        encoding="utf-8",
    )
    current_path = vault_root / "00-system" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text(
        json.dumps({"work": work_relative_path.as_posix()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)
    original_replace = os.replace

    def fail_inbox_replace(source: str | Path, target: str | Path) -> None:
        if Path(target) == inbox_path:
            raise PermissionError("Inbox write interrupted")
        original_replace(source, target)

    monkeypatch.setattr("edifice.inbox.os.replace", fail_inbox_replace)
    interrupted = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "current-work-note",
        ],
    )
    assert interrupted.exit_code != 0
    monkeypatch.setattr("edifice.inbox.os.replace", original_replace)
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )

    rerouted = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "personal-idea",
        ],
    )

    assert rerouted.exit_code != 0
    assert "Capture has incomplete route current-work-note." in rerouted.output
    assert not (
        vault_root / "10-personal" / "ai" / "ideas" / "capture-ideas.md"
    ).exists()
    assert work_path.read_text(encoding="utf-8").count("Keep this work note.") == 1


def test_inbox_route_rejects_work_idea_classification_change_on_retry(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    vault_root = tmp_path / "vault"
    inbox_path = vault_root / "01-inbox" / "inbox.md"
    inbox_path.parent.mkdir(parents=True)
    inbox_path.write_text(
        "# Inbox\n\n- [ ] work idea: improve review evidence.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "edifice.inbox._now",
        lambda: datetime(2026, 9, 13, 16, 0, tzinfo=UTC),
    )
    runner = CliRunner()
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "process",
            ],
        ).exit_code
        == 0
    )
    capture_match = re.search(
        r"\^(capture-[0-9a-f-]{36})",
        inbox_path.read_text(encoding="utf-8"),
    )
    assert capture_match is not None
    capture_id = capture_match.group(1)
    assert (
        runner.invoke(
            cli,
            [
                *_base_arguments(vault_root, tmp_path / "audit"),
                "inbox",
                "route",
                capture_id,
                "--to",
                "work-idea",
                "--classification",
                "public",
            ],
        ).exit_code
        == 0
    )

    retried = runner.invoke(
        cli,
        [
            *_base_arguments(vault_root, tmp_path / "audit"),
            "inbox",
            "route",
            capture_id,
            "--to",
            "work-idea",
            "--classification",
            "netflix-confidential",
        ],
    )

    assert retried.exit_code != 0
    assert "Capture already completed with classification public." in retried.output
