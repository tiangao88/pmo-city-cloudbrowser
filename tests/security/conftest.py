"""Shared Phase-0 RED boundary harness for the CloudFiles public gateway.

This module deliberately contains NO production CloudFiles code. It only
provides test doubles (a WSGI client, a fake downloads port, subject
resolvers) so the focused security tests can express the wished-for public
gateway boundary.

The optional production module `cloudbrowser.cloudfiles.api` does not exist
yet (Phase 0 RED). We therefore do NOT import it at module-load time. The
focused tests under `tests/security/test_cloudfiles_v1_gateway_security.py`
are gated behind the `gateway` pytest marker. They will skip cleanly when the
production module is absent and FAIL with a clear message once the production
module is added but lacks the expected surface.

The boundary test file `tests/contract/test_cloudfiles_v1_gateway_boundary.py`
imports `cloudbrowser.cloudfiles.*` modules directly via `importlib`. Those
modules do not yet exist; pytest will collect those tests and they will error
at import time, which is the intended Phase-0 RED signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrincipalBinding:
    """Test-local stand-in for the server-derived binding contract."""

    principal_id: str
    generation: str = "generation-0"
    revoked: bool = False


class MissingBinding(RuntimeError):
    """The authenticated subject cannot be resolved to a principal."""


class AmbiguousBinding(RuntimeError):
    """The authenticated subject maps to more than one principal."""


class RevokedBinding(RuntimeError):
    """The subject's binding has been revoked."""


class StaleBinding(RuntimeError):
    """The subject's binding generation is no longer current."""


@dataclass
class CallRecord:
    path: str
    headers: dict[str, str]
    binding: PrincipalBinding


@dataclass
class FakeDownloads:
    """In-memory stand-in for the internal downloads/v1 port."""

    store: dict[PrincipalBinding, list[dict[str, object]]] = field(
        default_factory=dict,
        kw_only=True,
    )
    calls: list[CallRecord] = field(default_factory=list, kw_only=True)

    def list_files(self, binding: PrincipalBinding, headers: dict[str, str]) -> dict:
        self.calls.append(CallRecord("/api/files", dict(headers), binding))
        return {"entries": list(self.store.get(binding, []))}

    def read_file(
        self,
        binding: PrincipalBinding,
        name: str,
        headers: dict[str, str],
    ) -> bytes | None:
        self.calls.append(CallRecord(f"/file/{name}", dict(headers), binding))
        for entry in self.store.get(binding, []):
            if entry["name"] == name:
                return b"%PDF-" + name.encode("utf-8")
        return None


def make_resolver(
    subject: str | None,
    *,
    revoked: bool = False,
    generation: str = "generation-0",
):
    """Return a server-owned resolver that trusts only the Authorization header."""

    def resolve(context: dict[str, str]) -> PrincipalBinding:
        if revoked:
            raise RevokedBinding(context.get("path", ""))
        if subject is None:
            raise MissingBinding(context.get("path", ""))
        return PrincipalBinding(principal_id=subject, generation=generation)

    return resolve


# ---------------------------------------------------------------------------
# Optional gateway app fixture (skips if production code absent)
# ---------------------------------------------------------------------------


@pytest.fixture
def gateway_app():
    """Boot the wished-for public gateway as a plain WSGI callable.

    Skips when the production module is missing so the broader suite still
    collects. Tests that require the gateway should be marked with
    `@pytest.mark.gateway` and will be collected once Phase 1 introduces the
    real implementation.
    """
    module = pytest.importorskip(
        "cloudbrowser.cloudfiles.api",
        reason="Phase 0: gateway production module is intentionally absent",
    )
    create_app = getattr(module, "create_cloudfiles_app", None)
    if create_app is None:  # pragma: no cover
        pytest.fail(
            "cloudbrowser.cloudfiles.api exists but does not expose "
            "create_cloudfiles_app(downloads, resolve_identity, server_identity)"
        )
    return create_app


# ---------------------------------------------------------------------------
# Minimal WSGI client
# ---------------------------------------------------------------------------


class WSGIResponse:
    def __init__(self, status: str, headers: list[tuple[str, str]], body: bytes) -> None:
        self.status = status
        self.status_code = int(status.split(" ", 1)[0])
        self.headers = {key.lower(): value for key, value in headers}
        self.body = body

    @property
    def json(self) -> dict:
        import json

        return json.loads(self.body.decode("utf-8"))


def wsgi_get(app, path: str, headers: dict[str, str] | None = None) -> WSGIResponse:
    """Run one GET through the WSGI callable without sockets."""
    captured: dict[str, object] = {}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = response_headers

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.url_scheme": "https",
    }
    if headers:
        for key, value in headers.items():
            key = key.upper().replace("-", "_")
            if key == "CONTENT_TYPE":
                environ["CONTENT_TYPE"] = value
            elif key == "CONTENT_LENGTH":
                environ["CONTENT_LENGTH"] = value
            else:
                environ[f"HTTP_{key}"] = value

    body = b"".join(app(environ, start_response))
    return WSGIResponse(
        status=str(captured.get("status", "500 Internal Server Error")),
        headers=list(captured.get("headers", [])),  # type: ignore[arg-type]
        body=body,
    )
