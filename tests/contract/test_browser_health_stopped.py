"""Boot-stopped browser health: a deliberately stopped browser is healthy.

With ``CB_BROWSER_AUTOSTART=0`` the browser container boots without Chrome
so the slot supervisor can adopt a server-minted binding first. The
container (and therefore the Coolify deployment) must still pass its
healthcheck in that state: ``GET /browser/health`` reports 200 with
``browser_state: "stopped"``, while ``/browser/readiness`` keeps failing
closed (503) because Chrome is genuinely not serving yet.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from cloudbrowser.browser_slots.browser_server import create_browser_server


class StubAdapter:
    owner = "principal-unassigned"
    generation = "generation-0"

    def readiness(self):
        class R:
            owner = StubAdapter.owner
            generation = StubAdapter.generation
            cdp_ok = False

        return R()


class StubProcess:
    state = "stopped"

    def readiness(self):
        return False


def _get(port: int, path: str) -> tuple[int, dict]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        resp = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        status = exc.code
    else:
        body = resp.read()
        status = resp.status
    return status, json.loads(body.decode("utf-8")) if body else {}


def _server():
    return create_browser_server(
        StubAdapter(),
        StubProcess(),
        instance_id="inst",
        release_version="0-test",
        address=("127.0.0.1", 0),
    )


def test_health_is_200_while_browser_is_stopped() -> None:
    server = _server()
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = _get(server.server_port, "/browser/health")
        assert status == 200
        assert payload["browser_state"] == "stopped"
        assert payload["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_readiness_stays_fail_closed_while_stopped() -> None:
    server = _server()
    thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _payload = _get(server.server_port, "/browser/readiness")
        assert status == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
