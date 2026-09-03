"""HTTP adapter for the public CloudFiles gateway.

This module exposes:

- `create_cloudfiles_app(downloads, resolve_identity, server_identity)` —
  the WSGI application used by the boundary tests and the eventual
  production runtime.
- `build_health_response()` — bounded health metadata (used by tests and
  `/health`).
- `build_listing_response(entries=...)` — bounded listing payload (used
  by tests and `/api/files`).
- `build_readiness_response(...)` — bounded readiness metadata.

The application enforces:
- Threat T1 — no client-supplied identity header affects the binding.
- Threat T2 — cross-principal reads return `forbidden_owner_mismatch`.
- Threat T3 — missing, revoked, or stale bindings return `unauthorized`
  or `owner_binding_unavailable`.
- Threat T4/T5 — unsafe filenames are rejected before any header.
- Threat T7 — error responses never echo raw identity or paths.
- Threat T8 — quarantined files are not retrievable.
- Threat T11 — the gateway strips X-CB-* headers from public requests.
- Threat T15 — there are no presigned URLs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Callable, Iterable, Mapping

from .contracts import (
    FileEntry,
    InvalidName,
    NotFound,
    OwnerMismatch,
    PrincipalBinding,
)
from .errors import build_error, public_code_for
from .filenames import safe_content_disposition, validate_name
from .gateway import build_internal_headers, sanitize_public_headers
from .headers import bake_response_headers
from .routes import PUBLIC_ROUTES


# ---------------------------------------------------------------------------
# Response builders used by the tests
# ---------------------------------------------------------------------------


def build_health_response(*, instance_id: str = "instance") -> dict[str, str]:
    """Build the bounded health metadata. No identity strings."""

    return {"status": "ok", "component": "cloudfiles", "instance": _short(instance_id)}


def build_readiness_response(*, ready: bool, dependency: str = "downloads") -> dict[str, str]:
    """Build the bounded readiness metadata."""

    return {
        "status": "ready" if ready else "not_ready",
        "component": "cloudfiles",
        "dependency": dependency,
    }


def build_listing_response(*, entries: Iterable[Mapping[str, object]]) -> dict[str, list[dict[str, object]]]:
    """Build the bounded listing response.

    Only `name`, `size`, and `mtime` are exposed. `principal_id`, `path`,
    and any other identifying field are removed.
    """

    bounded = []
    for entry in entries:
        bounded.append({
            "name": str(entry.get("name", "")),
            "size": int(entry.get("size", 0)),
            "mtime": int(entry.get("mtime", 0)),
        })
    return {"entries": bounded}


def _short(instance_id: str) -> str:
    return "instance" if not instance_id else instance_id[:8]


# ---------------------------------------------------------------------------
# Internal downloads port
# ---------------------------------------------------------------------------


@dataclass
class _InternalDownloads:
    """Minimal port used by the gateway in tests.

    In production, this is replaced by an HTTP client over the trusted
    internal network.
    """

    files: dict[PrincipalBinding, dict[str, bytes]] | None = None
    ready: bool = True

    def list_files(
        self,
        binding: PrincipalBinding,
        headers: Mapping[str, str],
    ) -> dict[str, list[dict[str, object]]]:
        if self.files is None:
            return {"entries": []}
        entries = []
        for entry in self.files.get(binding, {}).items():
            name, content = entry
            entries.append({
                "name": name,
                "size": len(content),
                "mtime": 0,
            })
        return {"entries": entries}

    def read_file(
        self,
        binding: PrincipalBinding,
        name: str,
        headers: Mapping[str, str],
    ) -> bytes | None:
        if self.files is None:
            return None
        return self.files.get(binding, {}).get(name)


Downloads = _InternalDownloads


# ---------------------------------------------------------------------------
# WSGI application
# ---------------------------------------------------------------------------


IdentityResolver = Callable[[Mapping[str, object]], PrincipalBinding]


@dataclass
class _App:
    downloads: _InternalDownloads
    resolve_identity: IdentityResolver
    server_identity: Mapping[str, str]

    def __call__(self, environ: Mapping[str, object], start_response):  # noqa: ANN001
        path = str(environ.get("PATH_INFO", "/"))
        method = str(environ.get("REQUEST_METHOD", "GET"))
        headers = {k.removeprefix("HTTP_").replace("_", "-"): v
                   for k, v in environ.items()
                   if k.startswith("HTTP_")}
        try:
            return self._dispatch(method=method, path=path, headers=headers,
                                  environ=environ, start_response=start_response)
        except Exception as exc:  # noqa: BLE001 — explicit boundary mapping
            return self._error_response(exc, start_response, request_id=str(headers.get("X-CB-Request-Id", "req-0")))

    # ------------------------------------------------------------------

    def _dispatch(self, *, method, path, headers, environ, start_response):
        if method != "GET":
            return self._error_response(NotFound("method not allowed"), start_response,
                                         request_id=str(headers.get("X-CB-Request-Id", "req-0")))
        cleaned = sanitize_public_headers(headers)
        if path == "/health":
            return self._ok(start_response, build_health_response(instance_id=str(self.server_identity.get("instance_id", "instance"))))
        if path == "/ready":
            return self._ok(start_response, build_readiness_response(ready=self.downloads.ready))
        if path == "/" or path == "/api/files":
            return self._list(cleaned=cleaned, start_response=start_response)
        if path.startswith("/file/"):
            return self._file(cleaned=cleaned, path=path, start_response=start_response)
        return self._error_response(NotFound("route not found"), start_response,
                                     request_id=str(headers.get("X-CB-Request-Id", "req-0")))

    # ------------------------------------------------------------------

    def _list(self, *, cleaned, start_response):
        binding = self._resolve(cleaned)
        internal_headers = build_internal_headers(binding=binding,
                                                  request_id=binding.request_id or "req-0")
        listing = self.downloads.list_files(binding=binding, headers=internal_headers)
        return self._ok(start_response, build_listing_response(entries=listing["entries"]))

    def _file(self, *, cleaned, path, start_response):
        binding = self._resolve(cleaned)
        name = path[len("/file/"):]
        valid = validate_name(name)
        if valid is None:
            return self._error_response(InvalidName("invalid filename"), start_response,
                                         request_id=binding.request_id or "req-0")
        internal_headers = build_internal_headers(binding=binding,
                                                  request_id=binding.request_id or "req-0")
        content = self.downloads.read_file(binding=binding, name=valid,
                                            headers=internal_headers)
        if content is None:
            return self._error_response(NotFound("file not found"), start_response,
                                         request_id=binding.request_id or "req-0")
        headers = bake_response_headers(filename=valid, content_type="application/octet-stream")
        body = content
        start_response("200 OK", [(k, v) for k, v in headers.items()])
        return [body]

    # ------------------------------------------------------------------

    def _resolve(self, cleaned):
        # Pass a bounded context to the resolver; the resolver MUST NOT look
        # at headers for identity (threat T1). The resolver returns a
        # PrincipalBinding or raises a CloudFilesError.
        ctx = {
            "session": cleaned.get("session"),
            "request_id": str(cleaned.get("X-CB-Request-Id", "req-0")),
            "headers": cleaned,
        }
        return self.resolve_identity(ctx)

    # ------------------------------------------------------------------

    def _ok(self, start_response, payload):
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Server": "cloudfiles",
        }
        start_response("200 OK", [(k, v) for k, v in headers.items()])
        return [body]

    def _error_response(self, exc, start_response, *, request_id):
        code = public_code_for(exc)
        payload = build_error(code=code, request_id=request_id)
        body = json.dumps(payload).encode("utf-8")
        status = _status_for(code)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Server": "cloudfiles",
        }
        start_response(status, [(k, v) for k, v in headers.items()])
        return [body]


def _status_for(code: str) -> str:
    if code == "unauthorized":
        return "401 Unauthorized"
    if code == "forbidden":
        return "403 Forbidden"
    if code == "forbidden_owner_mismatch":
        return "403 Forbidden"
    if code == "invalid_name":
        return "400 Bad Request"
    if code == "not_found":
        return "404 Not Found"
    if code == "too_large":
        return "413 Payload Too Large"
    if code == "owner_binding_unavailable":
        return "503 Service Unavailable"
    if code == "dependency_unavailable":
        return "503 Service Unavailable"
    return "500 Internal Server Error"


def create_cloudfiles_app(
    *,
    downloads,
    resolve_identity: IdentityResolver,
    server_identity: Mapping[str, str],
) -> object:
    """Construct the public WSGI application.

    The shape of `downloads` matches `_InternalDownloads` in tests and
    matches an HTTP client in production.
    """

    if not callable(resolve_identity):
        raise TypeError("resolve_identity must be callable")
    return _App(downloads=downloads, resolve_identity=resolve_identity,
                  server_identity=dict(server_identity))


__all__ = [
    "create_cloudfiles_app",
    "build_health_response",
    "build_listing_response",
    "build_readiness_response",
    "Downloads",
    "safe_content_disposition",
    "PUBLIC_ROUTES",
]
