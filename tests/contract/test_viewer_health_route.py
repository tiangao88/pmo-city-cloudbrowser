"""RED contract for the viewer image healthcheck endpoint."""

from __future__ import annotations

import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from cloudbrowser.viewer import AuthenticatedViewer, ViewerSessionStore, create_viewer_server


def test_viewer_health_is_unauthenticated_and_bounded() -> None:
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 100.0), token_secret=b"test-secret-012345")
    server = create_viewer_server(viewer, address=("127.0.0.1", 0))
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        response = urlopen(Request(f"http://{host}:{port}/health"))
        assert response.status == 200
        assert response.headers.get_content_type() == "application/json"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.read() == b'{"status":"ok","component":"viewer"}'
    finally:
        server.shutdown()
        server.server_close()


def test_viewer_health_does_not_replace_authentication_on_viewer_route() -> None:
    viewer = AuthenticatedViewer(ViewerSessionStore(clock=lambda: 100.0), token_secret=b"test-secret-012345")
    server = create_viewer_server(viewer, address=("127.0.0.1", 0))
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        with pytest.raises(HTTPError) as denied:
            urlopen(Request(f"http://{host}:{port}/viewer"))
        assert denied.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
