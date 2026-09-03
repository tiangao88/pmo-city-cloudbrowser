"""Phase 2 tests for the downloads HTTP boundary."""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.downloads.api import create_downloads_server
from cloudbrowser.downloads.contracts import ServerIdentity
from cloudbrowser.downloads.service import DownloadsService


def test_downloads_http_server_enforces_secret_and_owner_binding(tmp_path: Path) -> None:
    (tmp_path / "owner-a").mkdir()
    (tmp_path / "owner-a" / "legacy.txt").write_bytes(b"legacy")
    server = create_downloads_server(
        DownloadsService(store_root=tmp_path),
        server_identity=ServerIdentity("downloads", "phase2"),
        trusted_secret=b"s" * 32,
        address=("127.0.0.1", 0),
    )
    import threading
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(base + "/api/files"), timeout=2)
        assert denied.value.code == 401
        request = Request(base + "/api/files", headers={
            "X-CB-Trusted-Secret": "s" * 32,
            "X-CB-Principal": "owner-a",
            "X-CB-Request-Id": "request-a",
        })
        with urlopen(request, timeout=2) as response:
            assert response.status == 200
            assert b"legacy.txt" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
