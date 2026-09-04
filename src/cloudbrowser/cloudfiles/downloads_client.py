"""Typed HTTP client for the internal ``downloads/v1`` boundary."""

from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .contracts import PrincipalBinding
from .filenames import require_name


class DownloadsClientError(RuntimeError):
    """Bounded internal downloads client failure."""


class DownloadsTimeout(DownloadsClientError):
    """The internal service did not respond within its configured deadline."""


class DownloadsHttpError(DownloadsClientError):
    """The internal service returned a bounded non-success response."""

    def __init__(self, status: int, error_code: str = "dependency_unavailable") -> None:
        self.status = status
        self.error_code = error_code
        super().__init__(f"downloads returned HTTP {status}")


@dataclass(frozen=True)
class DownloadsClient:
    """Owner-bound client that supplies all trusted internal headers."""

    base_url: str
    shared_secret: str
    timeout_s: float = 3.0
    max_response_bytes: int = 8 * 1024 * 1024

    @property
    def ready(self) -> bool:
        """Report whether the internal downloads dependency responds."""
        try:
            with urlopen(
                Request(
                    self.base_url.rstrip("/") + "/health",
                    method="GET",
                    headers={"X-CB-Trusted-Secret": self.shared_secret},
                ),
                timeout=self.timeout_s,
            ) as response:
                body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    return False
                return True
        except (HTTPError, URLError, TimeoutError, OSError, DownloadsClientError):
            return False

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

    def _request(self, *, path: str, binding: PrincipalBinding, request_id: str) -> bytes:
        if not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("path must be a bounded route")
        request = Request(
            self.base_url.rstrip("/") + path,
            method="GET",
            headers=self.headers(binding, request_id=request_id),
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise DownloadsClientError("internal response exceeds size limit")
                return body
        except HTTPError as exc:
            error_code = "dependency_unavailable"
            try:
                payload = json.loads(exc.read(64 * 1024))
                if isinstance(payload, dict) and isinstance(payload.get("error_code"), str):
                    error_code = payload["error_code"]
            except (OSError, ValueError, TypeError):
                pass
            raise DownloadsHttpError(exc.code, error_code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise DownloadsTimeout("downloads dependency unavailable") from exc

    def list_files(self, *, binding: PrincipalBinding, request_id: str) -> dict[str, object]:
        payload = self._decode_json(
            self._request(path="/api/files", binding=binding, request_id=request_id),
        )
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise DownloadsClientError("invalid downloads listing")
        return {"entries": entries}

    def read_file(self, *, binding: PrincipalBinding, name: str, request_id: str) -> bytes | None:
        safe = require_name(name)
        try:
            return self._request(
                path="/file/" + quote(safe, safe=""),
                binding=binding,
                request_id=request_id,
            )
        except DownloadsHttpError as exc:
            if exc.status == 404:
                return None
            raise

    @staticmethod
    def _decode_json(body: bytes) -> dict[str, object]:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise DownloadsClientError("invalid downloads response") from exc
        if not isinstance(payload, dict):
            raise DownloadsClientError("invalid downloads response")
        return payload


__all__ = ["DownloadsClient", "DownloadsClientError", "DownloadsHttpError", "DownloadsTimeout"]
