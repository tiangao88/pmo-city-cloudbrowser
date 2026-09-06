"""Browser server must notify a listener when a binding push is accepted.

The listener is where the browser service rotates its download-watcher
attribution binding (and lazily builds the watcher in boot-stopped mode);
without it, downloads would be attributed to the stale boot binding.
"""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from cloudbrowser.browser_slots.browser_server import create_browser_server

SECRET = "test-shared-secret-0123456789"


class StubAdapter:
    owner = "principal-old"
    generation = "generation-old"

    def readiness(self):
        class R:
            owner = StubAdapter.owner
            generation = StubAdapter.generation
            cdp_ok = True
        return R()

    def rebind(self, owner, generation) -> None:
        StubAdapter.owner = owner
        StubAdapter.generation = generation


class StubProcess:
    state = "stopped"

    def readiness(self):
        return False

    def rebind(self, owner, generation) -> None:
        StubProcess.state = "stopped"


def _post_binding(port: int, payload: dict, secret: str = SECRET) -> int:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/browser/binding",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-CB-Trusted-Secret": secret},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_binding_push_notifies_listener(monkeypatch):
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", SECRET)
    seen: list[tuple[str, str]] = []
    server = create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="inst",
        release_version="0-test",
        address=("127.0.0.1", 0),
        binding_listener=lambda b: seen.append((b.principal_id, b.generation)),
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status = _post_binding(
            port,
            {
                "principal_id": "principal-new",
                "profile_id": "profile-new",
                "browser_id": "browser-1",
                "generation": "generation-new",
            },
        )
        assert status == 200
        assert seen == [("principal-new", "generation-new")]
    finally:
        server.shutdown()
        server.server_close()


def test_binding_push_failure_does_not_notify_listener(monkeypatch):
    monkeypatch.setenv("CB_ROUTER_SHARED_SECRET", SECRET)
    seen: list[object] = []
    server = create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="inst",
        release_version="0-test",
        address=("127.0.0.1", 0),
        binding_listener=seen.append,
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status = _post_binding(port, {"principal_id": "x"}, secret="wrong-secret-012345678")
        assert status in (400, 403)
        assert seen == []
    finally:
        server.shutdown()
        server.server_close()
