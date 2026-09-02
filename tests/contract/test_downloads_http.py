"""HTTP routing tests for the downloads service shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.downloads.identity import ServerIdentity
from cloudbrowser.downloads.api import create_downloads_server
from cloudbrowser.downloads.service import DownloadsService


@pytest.fixture
def server(tmp_path: Path):
    import socket
    import threading

    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "hello.pdf").write_bytes(b"%PDF-1")
    service = DownloadsService(store_root=tmp_path)
    identity = ServerIdentity(component="downloads", instance_id="cloudbrowser-dev-v01")
    server = create_downloads_server(
        service,
        server_identity=identity,
        trusted_secret=b"x" * 32,
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        socket.socket  # noqa: B018 - silence unused import


def _identity_headers(secret: bytes | None = None) -> dict[str, str]:
    headers: dict[str, str] = {
        "X-CB-Trusted-Secret": secret.decode("utf-8") if secret else "",
        "X-CB-Principal": "owner-a",
        "X-CB-Profile": "profile-a",
        "X-CB-Browser": "browser-1",
        "X-CB-Generation": "generation-1",
        "X-CB-Request-Id": "req-1",
    }
    return headers


def _request(server, path: str, *, secret: bytes | None = None):
    import urllib.request

    headers = _identity_headers(secret)
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}",
        headers=headers,
    )
    return urllib.request.urlopen(request, timeout=2)


def test_health_route_returns_bounded_metadata(server) -> None:
    with _request(server, "/health") as response:
        assert response.status == 200
        body = response.read()
    assert b'"status":"ok"' in body
    assert b'"component":"downloads"' in body


def test_untrusted_request_is_rejected(server) -> None:
    import urllib.error

    with pytest.raises(urllib.error.HTTPError) as exc:
        _request(server, "/api/files", secret=b"wrong-secret-padded-12345678")
    assert exc.value.code == 401


def test_listing_returns_only_principal_metadata(server) -> None:
    import json

    with _request(server, "/api/files", secret=b"x" * 32) as response:
        body = json.loads(response.read())
    assert body["principal_id"] == "owner-a"
    names = sorted(entry["name"] for entry in body["entries"])
    assert names == ["hello.pdf"]
    for entry in body["entries"]:
        assert entry["owner"] == "owner-a"


def test_file_route_serves_attachment_only(server) -> None:
    with _request(server, "/file/hello.pdf", secret=b"x" * 32) as response:
        assert response.status == 200
        assert response.headers.get("Content-Disposition", "").startswith("attachment")
        body = response.read()
    assert body == b"%PDF-1"


def test_file_route_rejects_traversal_attempts(server) -> None:
    import urllib.error

    with pytest.raises(urllib.error.HTTPError) as exc:
        _request(server, "/file/..%2Fetc%2Fpasswd", secret=b"x" * 32)
    assert exc.value.code in (400, 404)


def test_unknown_route_returns_404(server) -> None:
    import urllib.error

    with pytest.raises(urllib.error.HTTPError) as exc:
        _request(server, "/nope", secret=b"x" * 32)
    assert exc.value.code == 404
