"""Exercise the standalone local stack; synthetic auth only, no live accounts.

Run from the Mac after starting compose.candidate + compose.auth-fixture.
Only 127.0.0.1:18443 is contacted. Do not adapt this to a deployed endpoint.
"""
import http.client
import json
import ssl
import socket
import time
from wss_rfb import RfbWebSocket
from owner_switch import framebuffer

HOST = "desktop.example.test:18443"
ORIGIN = "https://" + HOST


def connect(cookie):
    connection = ssl._create_unverified_context().wrap_socket(
        socket.create_connection(("127.0.0.1", 18443), timeout=10), server_hostname="desktop.example.test")
    connection.sendall((f"GET /websockify HTTP/1.1\r\nHost: {HOST}\r\nOrigin: {ORIGIN}\r\n"
        "Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        f"Cookie: fixture_user=alice; {cookie}\r\n\r\n").encode())
    return connection


def call(path, *, user="alice", data=None, cookie="", host=HOST, extra=None):
    headers = {"Host": host, "Origin": ORIGIN}
    values = (["fixture_user=" + user] if user else []) + ([cookie] if cookie else [])
    if values:
        headers["Cookie"] = "; ".join(values)
    headers.update(extra or {})
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    client = http.client.HTTPSConnection("127.0.0.1", 18443, timeout=35,
        context=ssl._create_unverified_context())  # Dedicated local self-signed fixture only.
    try:
        client.request("POST" if data is not None else "GET", path, body=body, headers=headers)
        response = client.getresponse()
        raw = response.read()
        result = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
        return response.status, dict(response.getheaders()), result
    finally:
        client.close()


def main():
    assert call("/", user=None, extra={"Remote-Sub": "alice", "Remote-Groups": "PMOC_Users"})[0] == 401
    assert call("/ui/session/join", data=b"")[2]["status"] == "offered"
    status, _, active = call("/ui/session/activate", data=b"")
    assert status == 200 and active["status"] == "active", active.get("error_code")
    spoofed = call("/ui/session", extra={"Remote-Sub": "bob", "Remote-User": "bob"})[2]
    assert spoofed["session_id"] == active["session_id"], "edge did not replace caller identity"
    assert call("/ui/session", user="bob")[2]["status"] == "waiting"
    status, headers, _ = call("/ui/viewer/session", data=b"")
    assert status == 204
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert call("/desktop.html", cookie=cookie)[0] == 200
    stream = RfbWebSocket(cookie, connector=connect)
    try:
        assert len(framebuffer(stream)) == 1280 * 800 * 4
    finally:
        stream.close()
    assert call("/ui/agent/tabs_list", data={"params": {}})[2]["status"] == "ok"
    assert call("/ui/credential/login", data={})[0] == 503
    assert call("/v1/credential/login", host="router.example.test:18443", data={"request_id": "synthetic"})[2]["status"] == "failed"
    assert call("/ui/viewer/takeover", data=b"", cookie=cookie)[2]["mode"] == "human"
    assert call("/ui/agent/tabs_list", data={"params": {}})[2]["status"] != "ok"
    assert call("/ui/viewer/resume", data=b"", cookie=cookie)[2]["mode"] == "agent"
    assert call("/ui/agent/tabs_list", data={"params": {}})[2]["status"] == "ok"
    time.sleep(17)  # Longer than the 15s viewer lease: real supervisor must renew.
    assert call("/desktop.html", cookie=cookie)[0] == 200, "supervisor did not renew viewer lease"
    print("PASS actual Traefik → desktop → router → supervisor/browser/agent/identity-link", flush=True)
    print("PASS anonymous denial, identity-header replacement, activation, renewal, takeover, broker disabled", flush=True)
    for owner in ("bob", "alice"):
        prior = "alice" if owner == "bob" else "bob"
        assert call("/ui/session/leave", user=prior, data=b"")[2]["status"] == "left"
        assert call("/ui/session/join", user=owner, data=b"")[2]["status"] == "offered"
        active = call("/ui/session/activate", user=owner, data=b"")[2]
        assert active["status"] == "active", active.get("error_code")
        assert call("/desktop.html", user=owner, cookie=cookie)[0] == 403
        status, headers, _ = call("/ui/viewer/session", user=owner, data=b"")
        assert status == 204
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert call("/desktop.html", user=owner, cookie=cookie)[0] == 200
    assert call("/ui/session/leave", data=b"")[2]["status"] == "left"
    print("PASS actual-stack A/B/A via router; old viewer cookies denied", flush=True)


if __name__ == "__main__":
    main()
