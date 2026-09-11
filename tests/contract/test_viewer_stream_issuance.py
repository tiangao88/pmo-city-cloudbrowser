import http.client
from http.cookies import SimpleCookie
from threading import Thread
from types import SimpleNamespace

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding
from cloudbrowser.browser_slots.transport import BrowserReadiness
from cloudbrowser.viewer import AuthenticatedViewer, ViewerSessionStore, create_viewer_server
from cloudbrowser.viewer.slot_authority import SlotViewerAuthority
from cloudbrowser.viewer.transition import ViewerTransition

ORIGIN = "https://viewer.example.test"
HEADERS = {"Origin": ORIGIN, "Remote-Sub": "alice-sub", "Remote-Groups": "PMOC_Users"}
BINDING = BrowserBinding("p", "alice", "b", "g1")


@pytest.fixture
def rig():
    state = {"now": 0, "ready": True}
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: state["now"]), token_secret=b"synthetic-viewer-secret")
    resolver = SimpleNamespace(resolve=lambda identity: "alice" if identity.sub == "alice-sub" else "bob")
    authority = SlotViewerAuthority(viewer=viewer, identity_client=resolver,
        readiness=lambda: BrowserReadiness("alice", "g1", state["ready"]),
        stream_endpoint="/websockify", clock=lambda: state["now"])
    transition = ViewerTransition(authority, reset_display=lambda: None)
    ticket = transition.fence(BINDING)
    transition.enable(ticket, BINDING)
    server = create_viewer_server(viewer, address=("127.0.0.1", 0),
        allow_edge_identity=True, stream_authority=authority, public_origin=ORIGIN)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, authority, state, resolver
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def post(port, headers=HEADERS, body=None):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        client.request("POST", "/ui/viewer/session", body=body, headers=headers)
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


def test_current_sso_owner_receives_cookie_only(rig):
    port, authority, _, _ = rig
    status, headers, body = post(port)
    assert status == 204 and body == b""
    assert headers["Cache-Control"] == "no-store"
    cookie = SimpleCookie()
    cookie.load(headers["Set-Cookie"])
    value = cookie["__Host-CBViewer"]
    assert value["secure"] and value["httponly"]
    assert value["samesite"] == "Strict" and value["path"] == "/"
    live = authority.connect(trusted_headers=HEADERS, token=value.value,
        send_frame=lambda _: None, close_transport=lambda: None)
    assert live.forward_frame(b"synthetic-frame")


@pytest.mark.parametrize("headers", [
    {}, {"Origin": ORIGIN, "Remote-Email": "alice@example.test"},
    dict(HEADERS, Origin="https://wrong.example.test"),
    {"Origin": ORIGIN, "Remote-Sub": "alice-sub"},
    dict(HEADERS, **{"Remote-Sub": "bob-sub"}),
    {"Origin": ORIGIN, "Authorization": "Bearer synthetic-token"},
])
def test_untrusted_or_wrong_owner_requests_get_no_cookie(rig, headers):
    status, response, _ = post(rig[0], headers)
    assert status == 403 and "Set-Cookie" not in response


def test_caller_binding_json_is_rejected(rig):
    status, headers, _ = post(rig[0], body=b'{"principal_id":"alice"}')
    assert status == 403 and "Set-Cookie" not in headers


@pytest.mark.parametrize("failure", ["expired", "not-ready", "fenced", "identity-down"])
def test_authority_failure_never_mints_cookie(rig, failure):
    port, authority, state, resolver = rig
    if failure == "expired":
        state["now"] = 15
    elif failure == "not-ready":
        state["ready"] = False
    elif failure == "fenced":
        authority.fence(BINDING)
    else:
        resolver.resolve = lambda _: (_ for _ in ()).throw(RuntimeError("private detail"))
    status, headers, body = post(port)
    assert status == 403 and "Set-Cookie" not in headers
    assert b"private detail" not in body


@pytest.mark.parametrize("origin", [None, "http://viewer.example.test", ORIGIN + "/", ORIGIN + "?x=1"])
def test_issuer_requires_exact_https_origin(origin):
    with pytest.raises(ValueError):
        create_viewer_server(None, allow_edge_identity=True, stream_authority=object(), public_origin=origin)


def test_duplicate_identity_headers_rejected(rig):
    client = http.client.HTTPConnection("127.0.0.1", rig[0], timeout=2)
    try:
        client.putrequest("POST", "/ui/viewer/session")
        for key, value in HEADERS.items():
            client.putheader(key, value)
        client.putheader("remote-sub", "bob-sub")
        client.putheader("Content-Length", "0")
        client.endheaders()
        response = client.getresponse()
        assert response.status == 403 and response.getheader("Set-Cookie") is None
    finally:
        client.close()
