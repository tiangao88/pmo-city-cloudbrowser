"""Internal downloads HTTP server with bounded owner authorization."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Callable
from urllib.parse import unquote

from .contracts import PrincipalIdentity, ServerIdentity
from .identity import TrustedSecret, check_trusted_secret
from .service import DownloadsService
from .store import safe_name


@dataclass(frozen=True)
class _RequestContext:
    method: str
    path: str
    name: str | None
    headers: dict[str, str]


def _extract_name(path: str) -> str | None:
    if not path.startswith("/file/"):
        return None
    return unquote(path[len("/file/") :])


def _resolve_context(*, method: str, path: str, headers: dict[str, str], resolver):
    return resolver(_RequestContext(method=method, path=path, name=_extract_name(path), headers=headers))


def _build_handler(*, service, server_identity, trusted_secret, identity_resolver):
    class DownloadsHandler(BaseHTTPRequestHandler):
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

        def _bytes(self, body: bytes, *, filename: str) -> None:
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            headers = {key.lower(): value for key, value in self.headers.items()}
            if path == "/health":
                self._json(200, {
                    "status": "ok",
                    "component": server_identity.component,
                    "instance_id": server_identity.instance_id,
                })
                return
            if not check_trusted_secret(provided=headers, expected=trusted_secret):
                self._json(401, {"error_code": "unauthorized"})
                return
            try:
                identity = _resolve_context(
                    method="GET",
                    path=path,
                    headers=headers,
                    resolver=identity_resolver,
                )
                if path == "/api/files":
                    self._json(200, service.list_files(identity).public_dict())
                    return
                if path.startswith("/file/"):
                    name = _extract_name(path) or ""
                    safe = safe_name(name)
                    if safe is None:
                        self._json(400, {"error_code": "invalid_name"})
                        return
                    payload = service.read_file(identity, safe)
                    if payload is None:
                        self._json(404, {"error_code": "not_found"})
                        return
                    self._bytes(payload, filename=safe)
                    return
                self._json(404, {"error_code": "not_found"})
            except Exception:  # noqa: BLE001 - bounded public error boundary
                self._json(503, {"error_code": "dependency_unavailable"})

    return DownloadsHandler


def _default_identity_resolver(context: _RequestContext) -> PrincipalIdentity:
    principal_id = context.headers.get("x-cb-principal") or context.headers.get("x-cb-owner") or ""
    if not principal_id:
        from .contracts import OwnerMismatch
        raise OwnerMismatch("server-derived principal is required")
    return PrincipalIdentity(
        request_id=context.headers.get("x-cb-request-id", "req-1"),
        principal_id=principal_id,
        profile_id=context.headers.get("x-cb-profile", "profile-unassigned"),
        browser_id=context.headers.get("x-cb-browser", "browser-unassigned"),
        generation=context.headers.get("x-cb-generation", "generation-0"),
    )


def create_downloads_server(
    service: DownloadsService,
    *,
    server_identity: ServerIdentity,
    trusted_secret: bytes,
    address: tuple[str, int],
    identity_resolver: Callable[[_RequestContext], PrincipalIdentity] | None = None,
) -> ThreadingHTTPServer:
    """Create the bounded downloads HTTP server."""

    secret = TrustedSecret(trusted_secret)
    return ThreadingHTTPServer(
        address,
        _build_handler(
            service=service,
            server_identity=server_identity,
            trusted_secret=secret,
            identity_resolver=identity_resolver or _default_identity_resolver,
        ),
    )


__all__ = ["create_downloads_server", "_default_identity_resolver"]
