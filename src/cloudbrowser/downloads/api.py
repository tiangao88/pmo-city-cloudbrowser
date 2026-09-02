"""Bounded HTTP routing for the downloads service."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Callable
from urllib.parse import unquote

from .contracts import PrincipalIdentity, ServerIdentity
from .identity import TrustedSecret, check_trusted_secret
from .service import DownloadsService
from .store import owner_key, safe_name


@dataclass(frozen=True)
class _RequestContext:
    method: str
    path: str
    name: str | None
    headers: dict[str, str]


def _resolve_context(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    identity_resolver: Callable[[_RequestContext], PrincipalIdentity],
) -> PrincipalIdentity:
    context = _RequestContext(
        method=method,
        path=path,
        name=_extract_name(path),
        headers=headers,
    )
    return identity_resolver(context)


def _extract_name(path: str) -> str | None:
    if not path.startswith("/file/"):
        return None
    return unquote(path[len("/file/") :])


def _build_handler(
    *,
    service: DownloadsService,
    server_identity: ServerIdentity,
    trusted_secret: TrustedSecret,
    identity_resolver: Callable[[_RequestContext], PrincipalIdentity],
) -> type[BaseHTTPRequestHandler]:
    """Construct the HTTP handler bound to the trusted-server identity."""

    class DownloadsHandler(BaseHTTPRequestHandler):
        # `BaseHTTPRequestHandler.log_message` writes to stderr by default.
        # Override to silence per-request access logs (no sensitive payloads).
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
            return

        def _write_json(self, code: int, payload: dict[str, object] | list[object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _write_bytes(
            self,
            code: int,
            body: bytes,
            *,
            content_type: str,
            filename: str,
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            path = self.path.split("?", 1)[0]
            headers = {key.lower(): value for key, value in self.headers.items()}
            if path == "/health":
                self._write_json(
                    200,
                    {
                        "status": "ok",
                        "component": server_identity.component,
                        "instance_id": server_identity.instance_id,
                    },
                )
                return
            if not check_trusted_secret(provided=headers, expected=trusted_secret):
                self._write_json(401, {"error_code": "unauthorized"})
                return
            identity = _resolve_context(
                method="GET",
                path=path,
                headers=headers,
                identity_resolver=identity_resolver,
            )
            if path == "/api/files":
                response = service.list_files(identity)
                self._write_json(200, response.public_dict())
                return
            if path.startswith("/file/"):
                name = _extract_name(path) or ""
                safe = safe_name(name)
                if safe is None:
                    self._write_json(400, {"error_code": "invalid_name"})
                    return
                payload = service.read_file(identity, safe)
                if payload is None:
                    self._write_json(404, {"error_code": "not_found"})
                    return
                content_type = (
                    "application/pdf" if safe.lower().endswith(".pdf") else "application/octet-stream"
                )
                self._write_bytes(
                    200,
                    payload,
                    content_type=content_type,
                    filename=safe,
                )
                return
            self._write_json(404, {"error_code": "not_found"})

    return DownloadsHandler


def _default_identity_resolver(context: _RequestContext) -> PrincipalIdentity:
    """Resolve the server-derived identity from the trusted router headers."""

    principal_id = (
        context.headers.get("x-cb-principal")
        or context.headers.get("x-cb-owner")
        or ""
    )
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
    """Create the bounded downloads HTTP server with server-derived identity."""

    secret = TrustedSecret(trusted_secret)
    resolver = identity_resolver or _default_identity_resolver
    return ThreadingHTTPServer(
        address,
        _build_handler(
            service=service,
            server_identity=server_identity,
            trusted_secret=secret,
            identity_resolver=resolver,
        ),
        bind_and_activate=True,
    )


__all__ = [
    "create_downloads_server",
    "owner_key",
    "_default_identity_resolver",
]
