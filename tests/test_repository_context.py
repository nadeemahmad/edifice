import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[1]
REGISTRY_PATH = REPOSITORY_ROOT / "docs" / "workstreams" / "registry.json"
SCHEMA_PATH = REPOSITORY_ROOT / "docs" / "workstreams" / "registry.schema.json"
OWNER_PRACTICES_PATH = REPOSITORY_ROOT / "docs" / "engineering" / "owner-practices.md"
VAULT_OWNER_PRACTICES_PATH = (
    REPOSITORY_ROOT
    / "vault-template"
    / "00-system"
    / "engineering"
    / "owner-practices.md"
)
ASSIGNMENT_PATH = (
    REPOSITORY_ROOT / "docs" / "engineering" / "agent-assignment.example.json"
)
ASSIGNMENT_SCHEMA_PATH = (
    REPOSITORY_ROOT / "docs" / "engineering" / "agent-assignment.schema.json"
)
ALLOWED_STATUSES = {"planned", "designed", "active", "uncommitted", "committed"}
ALLOWED_MODES = {
    "research",
    "experiment",
    "design",
    "implementation",
    "verification",
    "review",
}


def test_workstream_registry_references_valid_unique_repository_context() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert registry["schema_version"] == 1
    assert schema["properties"]["schema_version"]["const"] == 1
    workstreams = registry["workstreams"]
    workstream_ids = [workstream["id"] for workstream in workstreams]
    assert len(workstream_ids) == len(set(workstream_ids))

    owned_paths: set[str] = set()
    for workstream in workstreams:
        assert workstream["status"] in ALLOWED_STATUSES
        assert workstream["mode"] in ALLOWED_MODES
        assert (REPOSITORY_ROOT / workstream["context"]).is_file()
        for path in workstream["owned_paths"]:
            assert path not in owned_paths
            assert (REPOSITORY_ROOT / path).exists()
            owned_paths.add(path)
        for path in workstream["shared_paths"]:
            assert (REPOSITORY_ROOT / path).exists()

    for path in registry["integration_owned_paths"]:
        assert (REPOSITORY_ROOT / path).exists()


def test_vault_template_uses_canonical_owner_engineering_practices() -> None:
    assert OWNER_PRACTICES_PATH.read_bytes() == VAULT_OWNER_PRACTICES_PATH.read_bytes()


def test_agent_assignment_limits_feature_agent_to_registered_owned_paths() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assignment = json.loads(ASSIGNMENT_PATH.read_text(encoding="utf-8"))
    schema = json.loads(ASSIGNMENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    workstreams = {
        workstream["id"]: workstream for workstream in registry["workstreams"]
    }

    assert assignment["schema_version"] == 1
    assert schema["properties"]["schema_version"]["const"] == 1
    assert assignment["workstream"] in workstreams
    assert assignment["branch"].startswith("nahmad/")
    assert assignment["branch"].endswith("-codex")
    assert set(assignment["writable_paths"]).issubset(
        workstreams[assignment["workstream"]]["owned_paths"]
    )
    assert not set(assignment["writable_paths"]).intersection(
        registry["integration_owned_paths"]
    )
