"""Scanner ports used by the Phase-2 ingest pipeline.

Phase 4 adds the production ClamAV adapter: a clamd client speaking the
INSTREAM protocol over TCP. Every failure mode (unreachable daemon, timeout,
malformed reply, oversized payload, missing file) returns the bounded
``error`` verdict so the ingest pipeline quarantines instead of publishing.
"""

from __future__ import annotations

import socket
import struct
from pathlib import Path
from typing import Protocol


class Scanner(Protocol):
    """Scan a staged file and return a bounded verdict."""

    def scan(self, path: Path, *, request_id: str) -> str:
        """Return ``clean`` or a non-clean verdict."""


class CleanScanner:
    """Explicit development scanner for tests and local wiring only."""

    def scan(self, path: Path, *, request_id: str) -> str:
        if not path.is_file():
            raise FileNotFoundError(path)
        return "clean"


class ClamAvScanner:
    """Production ClamAV adapter over the clamd INSTREAM TCP protocol.

    Verdicts are normalized to ``clean``, ``infected``, or ``error``.
    Anything other than an explicit clean reply is a fail-closed ``error``
    (the ingest pipeline quarantines non-clean verdicts).
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 3310,
        timeout_s: float = 10.0,
        max_bytes: int = 1024 * 1024 * 1024,
        chunk_bytes: int = 64 * 1024,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if max_bytes <= 0 or chunk_bytes <= 0:
            raise ValueError("scan limits must be positive")
        self.host = host
        self.port = int(port)
        self.timeout_s = float(timeout_s)
        self.max_bytes = int(max_bytes)
        self.chunk_bytes = int(chunk_bytes)

    def scan(self, path: Path, *, request_id: str) -> str:
        try:
            if not Path(path).is_file():
                return "error"
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_s
            ) as connection:
                connection.settimeout(self.timeout_s)
                connection.sendall(b"zINSTREAM\x00")
                sent = 0
                with Path(path).open("rb") as handle:
                    while True:
                        chunk = handle.read(self.chunk_bytes)
                        if not chunk:
                            break
                        sent += len(chunk)
                        if sent > self.max_bytes:
                            return "error"
                        connection.sendall(struct.pack(">I", len(chunk)) + chunk)
                connection.sendall(struct.pack(">I", 0))
                reply = self._read_reply(connection)
        except (OSError, TimeoutError, socket.timeout, struct.error):
            return "error"
        return self._verdict(reply)

    @staticmethod
    def _read_reply(connection: socket.socket) -> str:
        data = bytearray()
        while True:
            chunk = connection.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
            if b"\n" in data:
                break
        return data.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _verdict(reply: str) -> str:
        lowered = reply.lower()
        if "found" in lowered:
            return "infected"
        if lowered.startswith("ok") or "stream: ok" in lowered:
            return "clean"
        return "error"


__all__ = ["CleanScanner", "ClamAvScanner", "Scanner"]
