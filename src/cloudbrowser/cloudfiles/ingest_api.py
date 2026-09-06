"""Internal CloudFiles ingest receiver: authenticated, bounded, pipeline-bound.

This is the cloudfiles-side half of the production browser-download transport.
It is an internal-only HTTP listener (never the public gateway): the browser
service streams a completed download here under the trusted secret and the
allowlisted binding headers, and the receiver feeds the existing
scan-before-publish ``IngestPipeline``.

Boundary invariants:
- every route except ``GET /health`` requires the trusted secret;
- the owner binding comes only from the allowlisted ``X-CB-*`` headers;
- ``Content-Length`` larger than the configured cap is rejected before any
  body byte is read;
- the body is never read past its declared ``Content-Length``;
- responses carry only the bounded receipt (no principal, no paths).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from cloudbrowser.downloads.contracts import ServerIdentity
from cloudbrowser.downloads.identity import TrustedSecret, check_trusted_secret

from .contracts import CloudFilesError, InvalidName, PrincipalBinding, TooLarge
from .ingest import IngestPipeline

DEFAULT_INGEST_MAX_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class _RequestContext:
    method: str
    path: str
    headers: dict[str, str]


def _default_binding_resolver(context: _RequestContext) -> PrincipalBinding:
    """Resolve the binding from allowlisted internal headers only."""

    principal_id = context.headers.get("x-cb-principal") or ""
    if not principal_id:
        raise ValueError("server-derived principal is required")
    return PrincipalBinding(
        principal_id=principal_id,
        profile_id=context.headers.get("x-cb-profile", "profile-unassigned"),
        browser_id=context.headers.get("x-cb-browser", "browser-unassigned"),
        generation=context.headers.get("x-cb-generation", "generation-0"),
        request_id=context.headers.get("x-cb-request-id", "req-ingest"),
    )


class _BoundedReader:
    """Serve at most ``declared`` wire bytes, never exceeding ``max_bytes``."""

    def __init__(self, stream, *, max_bytes: int, declared: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes
        self._declared = declared
        self._total = 0

    def read(self, n: int = -1) -> bytes:
        if self._total >= self._declared:
            return b""
        if n is None or n < 0:
            n = self._declared - self._total
        n = min(n, self._declared - self._total)
        if n <= 0:
            return b""
        chunk = self._stream.read(n)
        self._total += len(chunk)
        if self._total > self._max_bytes:
            raise TooLarge("ingest exceeds size limit")
        return chunk


def _build_handler(*, pipeline, server_identity, trusted_secret, max_bytes, binding_resolver):
    class IngestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _json(self, code: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._json(
                    200,
                    {
                        "status": "ok",
                        "component": server_identity.component,
                        "instance_id": server_identity.instance_id,
                    },
                )
                return
            self._json(404, {"error_code": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path != "/ingest/complete":
                self._json(404, {"error_code": "not_found"})
                return
            headers = {key.lower(): value for key, value in self.headers.items()}
            if not check_trusted_secret(provided=headers, expected=trusted_secret):
                self._json(401, {"error_code": "unauthorized"})
                return
            try:
                binding = binding_resolver(
                    _RequestContext(method="POST", path=path, headers=headers)
                )
            except ValueError:
                self._json(400, {"error_code": "invalid_binding"})
                return
            try:
                declared = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(400, {"error_code": "invalid_length"})
                return
            if declared < 0:
                self._json(400, {"error_code": "invalid_length"})
                return
            if declared > max_bytes:
                self._json(413, {"error_code": "too_large"})
                return
            try:
                receipt = pipeline.ingest(
                    binding=binding,
                    source_name=headers.get("x-cb-filename", ""),
                    source=_BoundedReader(self.rfile, max_bytes=max_bytes, declared=declared),
                )
            except InvalidName:
                self._json(400, {"error_code": "invalid_name"})
                return
            except TooLarge:
                self._json(413, {"error_code": "too_large"})
                return
            except CloudFilesError:
                self._json(503, {"error_code": "dependency_unavailable"})
                return
            except Exception:  # noqa: BLE001 - bounded public error boundary
                self._json(503, {"error_code": "dependency_unavailable"})
                return
            self._json(
                200,
                {
                    "name": receipt.name,
                    "size": receipt.size,
                    "status": receipt.status,
                    "request_id": receipt.request_id,
                    "sha256": receipt.sha256 or "",
                },
            )

    return IngestHandler


def create_ingest_server(
    pipeline: IngestPipeline,
    *,
    server_identity: ServerIdentity,
    trusted_secret: bytes,
    address: tuple[str, int],
    max_bytes: int = DEFAULT_INGEST_MAX_BYTES,
    binding_resolver: Callable[[_RequestContext], PrincipalBinding] | None = None,
) -> ThreadingHTTPServer:
    """Create the internal, authenticated CloudFiles ingest receiver."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    return ThreadingHTTPServer(
        address,
        _build_handler(
            pipeline=pipeline,
            server_identity=server_identity,
            trusted_secret=TrustedSecret(trusted_secret),
            max_bytes=max_bytes,
            binding_resolver=binding_resolver or _default_binding_resolver,
        ),
    )


__all__ = ["DEFAULT_INGEST_MAX_BYTES", "create_ingest_server", "_default_binding_resolver"]
