"""Typed HTTP client for the internal CloudFiles ingest receiver.

The browser service uses this client for the secure local-filesystem handoff:
only allowlisted binding headers and the trusted secret leave the browser
side, the request is bounded by an explicit Content-Length without buffering
the whole stream, and responses are capped and validated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import PrincipalBinding
from .filenames import require_name
from .ingest import IngestReceipt


class IngestClientError(RuntimeError):
    """Bounded internal ingest client failure."""


class IngestTimeout(IngestClientError):
    """The internal ingest receiver did not respond within its deadline."""


class IngestHttpError(IngestClientError):
    """The internal ingest receiver returned a bounded non-success response."""

    def __init__(self, status: int, error_code: str = "dependency_unavailable") -> None:
        self.status = status
        self.error_code = error_code
        super().__init__(f"ingest returned HTTP {status}")


class _ChunkedSource:
    """Stream a binary source as byte chunks without buffering it."""

    def __init__(self, source: BinaryIO, chunk_bytes: int = 64 * 1024) -> None:
        self._source = source
        self._chunk_bytes = chunk_bytes

    def __iter__(self) -> "_ChunkedSource":
        return self

    def __next__(self) -> bytes:
        chunk = self._source.read(self._chunk_bytes)
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError("source must yield bytes")
        if not chunk:
            raise StopIteration
        return bytes(chunk)


@dataclass(frozen=True)
class IngestClient:
    """Owner-bound client that supplies the trusted internal header set."""

    base_url: str
    shared_secret: str
    timeout_s: float = 3.0
    max_response_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        if not isinstance(self.shared_secret, str) or len(self.shared_secret.encode("utf-8")) < 16:
            raise ValueError("shared_secret must be at least 16 bytes")
        if self.timeout_s <= 0 or self.max_response_bytes <= 0:
            raise ValueError("client limits must be positive")

    def headers(self, binding: PrincipalBinding, *, request_id: str) -> dict[str, str]:
        """Build a fresh allowlisted trusted request header set."""

        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id is required")
        return {
            "X-CB-Trusted-Secret": self.shared_secret,
            "X-CB-Principal": binding.principal_id,
            "X-CB-Profile": binding.profile_id,
            "X-CB-Browser": binding.browser_id,
            "X-CB-Generation": binding.generation,
            "X-CB-Request-Id": request_id,
        }

    def submit(
        self, *, binding: PrincipalBinding, source_name: str, source: BinaryIO, size: int
    ) -> IngestReceipt:
        """Stream one completed download to the internal ingest receiver."""

        safe = require_name(source_name)
        if not isinstance(size, int) or size < 0:
            raise IngestClientError("size must be a non-negative integer")
        if not hasattr(source, "read"):
            raise TypeError("source must be a binary stream")
        request = Request(
            self.base_url.rstrip("/") + "/ingest/complete",
            data=_ChunkedSource(source),
            method="POST",
            headers={
                **self.headers(binding, request_id=binding.request_id),
                "Content-Length": str(size),
                "X-CB-Filename": safe,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise IngestClientError("ingest response exceeds size limit")
        except HTTPError as exc:
            error_code = "dependency_unavailable"
            try:
                payload = json.loads(exc.read(64 * 1024))
                if isinstance(payload, dict) and isinstance(payload.get("error_code"), str):
                    error_code = payload["error_code"]
            except (OSError, ValueError, TypeError):
                pass
            raise IngestHttpError(exc.code, error_code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise IngestTimeout("ingest dependency unavailable") from exc
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise IngestClientError("invalid ingest receipt") from exc
        if not isinstance(payload, dict):
            raise IngestClientError("invalid ingest receipt")
        try:
            return IngestReceipt(
                name=str(payload["name"]),
                size=int(payload["size"]),
                status=str(payload["status"]),
                request_id=str(payload["request_id"]),
                sha256=str(payload.get("sha256") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IngestClientError("invalid ingest receipt") from exc


__all__ = ["IngestClient", "IngestClientError", "IngestHttpError", "IngestTimeout"]
