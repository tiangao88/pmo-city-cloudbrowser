"""Phase 4 ClamAV adapter contracts (clamd INSTREAM over TCP).

The scanner port (``Scanner``) must fail closed: any non-clean, malformed,
oversized, or unreachable result is a bounded verdict the ingest pipeline
treats as quarantined — never a crash and never silent publication.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest

from cloudbrowser.cloudfiles.scanner import ClamAvScanner


def _clamd_stub(reply: bytes):
    """Serve a single scripted clamd INSTREAM exchange on an ephemeral port."""

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def accept_once():
        connection, _ = server.accept()
        try:
            data = b""
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data += chunk
                if data.endswith(b"\x00\x00\x00\x00"):
                    break
            connection.sendall(reply)
        finally:
            connection.close()

    thread = threading.Thread(target=accept_once, daemon=True)
    thread.start()
    return server, thread


def _scanner(server, *, timeout_s: float = 2.0) -> ClamAvScanner:
    return ClamAvScanner(
        host="127.0.0.1",
        port=int(server.getsockname()[1]),
        timeout_s=timeout_s,
    )


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"payload-bytes")
    return path


def test_clamav_clean_reply_maps_to_clean(sample: Path) -> None:
    server, thread = _clamd_stub(b"stream: OK\n")
    try:
        assert _scanner(server).scan(sample, request_id="req-1") == "clean"
    finally:
        server.close()
        thread.join(timeout=3)


def test_clamav_found_reply_maps_to_infected(sample: Path) -> None:
    server, thread = _clamd_stub(b"stream: Eicar-Test-Signature FOUND\n")
    try:
        assert _scanner(server).scan(sample, request_id="req-1") == "infected"
    finally:
        server.close()
        thread.join(timeout=3)


def test_clamav_error_reply_fails_closed(sample: Path) -> None:
    server, thread = _clamd_stub(b"ERROR: size limit exceeded\n")
    try:
        assert _scanner(server).scan(sample, request_id="req-1") == "error"
    finally:
        server.close()
        thread.join(timeout=3)


def test_clamav_unreachable_scanner_fails_closed(sample: Path) -> None:
    scanner = ClamAvScanner(host="127.0.0.1", port=1, timeout_s=0.2)
    assert scanner.scan(sample, request_id="req-1") == "error"


def test_clamav_rejects_missing_file() -> None:
    scanner = ClamAvScanner(host="127.0.0.1", port=1, timeout_s=0.2)
    assert scanner.scan(Path("/nonexistent/nope.bin"), request_id="req-1") == "error"
