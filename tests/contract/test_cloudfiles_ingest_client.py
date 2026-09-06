"""Typed ingest client contract tests (RED first).

``IngestClient`` is the browser-side wire client for the internal CloudFiles
ingest receiver. It must send only the allowlisted binding headers, bound the
request by Content-Length without buffering the whole stream, cap responses,
and surface bounded errors.
"""

from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest

from cloudbrowser.cloudfiles.contracts import PrincipalBinding
from cloudbrowser.cloudfiles.ingest import IngestReceipt


def _binding() -> PrincipalBinding:
    return PrincipalBinding(
        principal_id="owner-a@example.test",
        profile_id="profile-a",
        browser_id="browser-a",
        generation="generation-a",
        request_id="request-a",
    )


def _client(**kwargs):
    from cloudbrowser.cloudfiles.ingest_client import IngestClient

    return IngestClient(
        base_url=kwargs.pop("base_url", "http://ingest:8086"),
        shared_secret=kwargs.pop("shared_secret", "client-secret-0123456789abcdef"),
        **kwargs,
    )


def test_client_rejects_invalid_configuration() -> None:
    from cloudbrowser.cloudfiles.ingest_client import IngestClient

    with pytest.raises(ValueError):
        IngestClient(base_url="ftp://ingest", shared_secret="s" * 32)
    with pytest.raises(ValueError):
        IngestClient(base_url="http://ingest:8086", shared_secret="short")
    with pytest.raises(ValueError):
        IngestClient(base_url="http://ingest:8086", shared_secret="s" * 32, timeout_s=0)
    with pytest.raises(ValueError):
        IngestClient(base_url="http://ingest:8086", shared_secret="s" * 32, max_response_bytes=0)


def test_client_headers_are_allowlisted() -> None:
    client = _client()
    headers = client.headers(_binding(), request_id="request-b")
    assert headers == {
        "X-CB-Trusted-Secret": "client-secret-0123456789abcdef",
        "X-CB-Principal": "owner-a@example.test",
        "X-CB-Profile": "profile-a",
        "X-CB-Browser": "browser-a",
        "X-CB-Generation": "generation-a",
        "X-CB-Request-Id": "request-b",
    }
    assert "Remote-Email" not in headers
    assert "X-CB-Owner" not in headers


def test_client_rejects_unsafe_names_and_non_stream_sources() -> None:
    from cloudbrowser.cloudfiles.contracts import InvalidName
    from cloudbrowser.cloudfiles.ingest_client import IngestClientError

    client = _client()
    with pytest.raises(InvalidName):
        client.submit(binding=_binding(), source_name="../evil.pdf", source=BytesIO(b"x"), size=1)
    with pytest.raises(TypeError):
        client.submit(binding=_binding(), source_name="ok.txt", source=b"not-a-stream", size=7)
    with pytest.raises(IngestClientError):
        client.submit(binding=_binding(), source_name="ok.txt", source=BytesIO(b"x"), size=-1)


def test_client_timeout_is_bounded(monkeypatch) -> None:
    from cloudbrowser.cloudfiles.ingest_client import IngestClientError, IngestTimeout

    client = _client(timeout_s=0.5)

    def fail(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr("cloudbrowser.cloudfiles.ingest_client.urlopen", fail)
    with pytest.raises(IngestTimeout):
        client.submit(binding=_binding(), source_name="ok.txt", source=BytesIO(b"payload"), size=7)
    assert issubclass(IngestTimeout, IngestClientError)


def test_client_http_error_carries_bounded_error_code(monkeypatch) -> None:
    from cloudbrowser.cloudfiles.ingest_client import IngestHttpError

    client = _client()

    def http_error(*args, **kwargs):
        raise HTTPError(
            "http://ingest/ingest/complete",
            413,
            "too large",
            {},
            BytesIO(b'{"error_code":"too_large"}'),
        )

    monkeypatch.setattr("cloudbrowser.cloudfiles.ingest_client.urlopen", http_error)
    with pytest.raises(IngestHttpError) as caught:
        client.submit(binding=_binding(), source_name="big.bin", source=BytesIO(b"x" * 10), size=10)
    assert caught.value.status == 413
    assert caught.value.error_code == "too_large"


def test_client_rejects_malformed_receipt(monkeypatch) -> None:
    from cloudbrowser.cloudfiles.ingest_client import IngestClientError

    client = _client()

    class Response:
        def read(self, n: int = -1) -> bytes:
            return b'{"name":"","size":0,"status":"published","request_id":"request-a"}'

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    def ok(*args, **kwargs):
        return Response()

    monkeypatch.setattr("cloudbrowser.cloudfiles.ingest_client.urlopen", ok)
    with pytest.raises(IngestClientError, match="receipt"):
        client.submit(binding=_binding(), source_name="ok.txt", source=BytesIO(b"x"), size=1)


def test_client_decodes_valid_receipt(monkeypatch) -> None:
    client = _client()

    class Response:
        def read(self, n: int = -1) -> bytes:
            return b'{"name":"report.pdf","size":7,"status":"published","request_id":"request-a","sha256":"' + b"a" * 64 + b'"}'

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

    def ok(*args, **kwargs):
        return Response()

    monkeypatch.setattr("cloudbrowser.cloudfiles.ingest_client.urlopen", ok)
    receipt = client.submit(binding=_binding(), source_name="report.pdf", source=BytesIO(b"payload"), size=7)
    assert isinstance(receipt, IngestReceipt)
    assert receipt.name == "report.pdf"
    assert receipt.status == "published"
    assert receipt.request_id == "request-a"
    assert receipt.sha256 == "a" * 64
