import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from app_base.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = PROJECT_ROOT / "docs" / "diddiconnect"
SCHEMA_PATH = CONTRACT_ROOT / "diddiconnect.module.v1.schema.json"
BOOTSTRAP_MANIFEST_ROOT = CONTRACT_ROOT / "manifests"
SERVICE_MANIFEST_ROOT = PROJECT_ROOT / "manifests"
SERVICE_MANIFEST_PATH = SERVICE_MANIFEST_ROOT / "diddicomms.v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_paths() -> list[Path]:
    return sorted(
        [
            *BOOTSTRAP_MANIFEST_ROOT.glob("*.json"),
            *SERVICE_MANIFEST_ROOT.glob("*.json"),
        ]
    )


def test_diddiconnect_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_load(SCHEMA_PATH))


def test_all_diddiconnect_manifests_conform_to_schema_and_module_scopes() -> None:
    validator = Draft202012Validator(_load(SCHEMA_PATH))
    manifest_paths = _manifest_paths()

    assert manifest_paths
    for path in manifest_paths:
        manifest = _load(path)
        errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.path))
        assert not errors, [f"{path}: {list(error.path)}: {error.message}" for error in errors]

        scope_prefix = f"{manifest['module']}:"
        owner_contexts = [
            *manifest["task_contexts"],
            *manifest.get("support_contexts", []),
        ]
        assert all(item["required_scope"].startswith(scope_prefix) for item in owner_contexts)


def test_implemented_task_contexts_have_no_placeholder_state_policy() -> None:
    for path in _manifest_paths():
        manifest = _load(path)
        for context in manifest["task_contexts"]:
            if context["status"] != "implemented":
                continue

            states = {policy["state"] for policy in context["state_policies"]}
            assert "owner_defined" not in states, path


def test_non_implemented_connections_explain_their_blocker() -> None:
    for path in _manifest_paths():
        manifest = _load(path)
        for connection in manifest["connections"]:
            if connection["status"] == "implemented":
                continue
            assert connection.get("blocking_reason"), f"{path}: {connection['peer_module']}"


def test_every_connection_references_an_existing_contract_document() -> None:
    for path in _manifest_paths():
        manifest = _load(path)
        for connection in manifest["connections"]:
            contract_path = PROJECT_ROOT / connection["contract"]
            assert contract_path.is_file(), f"{path}: missing {contract_path}"


def test_diddicomms_manifest_http_routes_exist_in_runtime_openapi() -> None:
    manifest = _load(SERVICE_MANIFEST_PATH)
    openapi_paths = app.openapi()["paths"]

    for route in [*manifest["http"]["user_routes"], *manifest["http"]["service_routes"]]:
        assert route["path"] in openapi_paths
        assert route["method"].lower() in openapi_paths[route["path"]]


def test_diddicomms_manifest_websocket_routes_exist_at_runtime() -> None:
    manifest = _load(SERVICE_MANIFEST_PATH)
    runtime_paths = {path for route in app.routes if (path := getattr(route, "path", None))}
    for included in (route for route in app.routes if hasattr(route, "original_router")):
        prefix = included.include_context.prefix
        runtime_paths.update(
            f"{prefix}{nested.path}"
            for nested in included.original_router.routes
            if getattr(nested, "path", None)
        )

    for websocket in manifest["websockets"]:
        declared_path = websocket["path"].split("?", maxsplit=1)[0]
        assert declared_path in runtime_paths


def test_diddicomms_manifest_lists_every_emitted_event_type() -> None:
    manifest = _load(SERVICE_MANIFEST_PATH)
    declared = {event["name"] for event in manifest["events"]["published"]}
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((PROJECT_ROOT / "app_base").rglob("*.py"))
    )
    emitted = set(re.findall(r'event_type\s*=\s*"([^"]+)"', source))

    assert emitted
    assert declared == emitted


def test_contract_fixtures_are_valid_json_and_do_not_contain_secrets() -> None:
    fixture_paths = sorted((CONTRACT_ROOT / "fixtures").glob("*.json"))
    assert fixture_paths

    forbidden_keys = {"client_secret", "access_token", "refresh_token", "private_key"}
    for path in fixture_paths:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        assert forbidden_keys.isdisjoint(_all_keys(payload)), path
        assert "BEGIN PRIVATE KEY" not in raw


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()
