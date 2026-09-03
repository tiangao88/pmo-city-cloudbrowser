"""Phase 2 contract tests for the internal downloads HTTP client."""

from __future__ import annotations

from pathlib import Path

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.downloads_client import (
    DownloadsClient,
    DownloadsClientError,
    DownloadsHttpError,
)


def _binding() -> PrincipalBinding:
    return PrincipalBinding(
        principal_id="owner-a@example.test",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
        request_id="request-a",
    )


def test_client_uses_allowlisted_trusted_headers_and_fresh_request_id(monkeypatch) -> None:
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size): return b'{"entries": []}'

    def fake_urlopen(request, *, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["url"] = request.full_url
        return Response()

    monkeypatch.setattr("cloudbrowser.cloudfiles.downloads_client.urlopen", fake_urlopen)
    client = DownloadsClient("http://downloads:8083", "s" * 32, timeout_s=1.25)
    assert client.list_files(binding=_binding(), request_id="request-z") == {"entries": []}
    assert captured["timeout"] == 1.25
    assert captured["url"] == "http://downloads:8083/api/files"
    assert captured["headers"]["X-cb-trusted-secret"] == "s" * 32
    assert captured["headers"]["X-cb-principal"] == "owner-a@example.test"
    assert captured["headers"]["X-cb-request-id"] == "request-z"
    assert "Remote-Email" not in captured["headers"]


def test_client_bounds_json_and_binary_responses(monkeypatch) -> None:
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size): return b"x" * 11

    monkeypatch.setattr("cloudbrowser.cloudfiles.downloads_client.urlopen", lambda *a, **k: Response())
    client = DownloadsClient("http://downloads:8083", "s" * 16, max_response_bytes=10)
    with pytest.raises(DownloadsClientError, match="exceeds size"):
        client.read_file(binding=_binding(), name="a.txt", request_id="request-a")


def test_client_preserves_bounded_http_error_status_and_code(monkeypatch) -> None:
    from urllib.error import HTTPError
    error = HTTPError(
        "http://downloads:8083/api/files", 401, "unauthorized", {},
        __import__("io").BytesIO(b'{"error_code":"unauthorized"}'),
    )
    monkeypatch.setattr("cloudbrowser.cloudfiles.downloads_client.urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
    client = DownloadsClient("http://downloads:8083", "s" * 16)
    with pytest.raises(DownloadsHttpError) as caught:
        client.list_files(binding=_binding(), request_id="request-a")
    assert caught.value.status == 401
    assert caught.value.error_code == "unauthorized"
