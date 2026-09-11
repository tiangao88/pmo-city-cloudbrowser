import http.client
from threading import Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.browser_server import create_browser_server
from cloudbrowser.viewer import create_viewer_server
from cloudbrowser.viewer.interaction import InteractionGate


@pytest.mark.parametrize("mode", ["paused", "human"])
@pytest.mark.parametrize("path,method", [
    ("/agent/pages", "GET"), ("/agent/pages/info?target_tab_id=test", "GET"),
    ("/agent/pages/open", "POST"), ("/broker/basic/probe", "POST"),
    ("/broker/basic/submit", "POST"), ("/broker/authentik/identification", "POST"),
])
def test_paused_http_requests_never_reach_adapter(mode, path, method):
    gate = InteractionGate()
    gate.change(mode)
    # No adapter methods exist: a request reaching one would fail this test.
    server = create_browser_server(SimpleNamespace(), SimpleNamespace(),
        instance_id="test", release_version="test", address=("127.0.0.1", 0), interaction_gate=gate)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        client.request(method, path, body=b"{}" if method == "POST" else None)
        response = client.getresponse()
        assert response.status == 503
        assert b"browser_control_paused" in response.read()
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_disabled_credential_ui_does_not_call_upstream_router():
    server = create_viewer_server(None, address=("127.0.0.1", 0),
        session_surface=SimpleNamespace(), allow_edge_identity=True, credential_login_enabled=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        client.request("POST", "/ui/credential/login", body=b"{}")
        response = client.getresponse()
        assert response.status == 503
        assert b"credential_login_disabled" in response.read()
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
