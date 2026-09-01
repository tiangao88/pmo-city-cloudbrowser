import json
import threading
import urllib.request

from cloudbrowser.health import create_health_server, health_payload


def test_health_payload_contains_only_non_sensitive_installation_metadata():
    payload = health_payload(
        component="router",
        instance_id="cloudbrowser-test",
        release_version="0.2.0-dev1",
    )
    assert payload == {
        "status": "ok",
        "component": "router",
        "instance_id": "cloudbrowser-test",
        "release_version": "0.2.0-dev1",
    }
    assert not any(secret in json.dumps(payload).lower() for secret in ("password", "token", "cookie"))


def test_health_endpoint_is_live_and_component_specific():
    server = create_health_server(
        component="viewer",
        instance_id="cloudbrowser-test",
        release_version="0.2.0-dev1",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/health", timeout=2
        ) as response:
            assert response.status == 200
            assert json.load(response)["component"] == "viewer"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
