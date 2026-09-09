"""Runtime wiring for the credential-broker service (Layer 3).

Assembles the full broker stack from environment configuration:

- ``BrokerHttpServer`` (status-only transport, ``api.py``);
- ``BrokerCoordinator`` (binding checks, idempotency, audit);
- ``VaultwardenClient`` (per-call unlock producer, ``vault_client.py``);
- a real HTTPS/HTTP transport over ``urllib`` (host header pinned).

Environment:
- ``CB_VAULT_BASE_URL`` (required, e.g. https://vaultwarden.internal);
- ``CB_VAULT_EMAIL`` / ``CB_VAULT_PASSWORD`` (required; passed by the
  platform secret store, never written to disk or logs);
- ``CB_BROKER_SHARED_SECRET`` (required; callers must present it as
  ``X-CB-Broker-Secret``);
- ``CB_BROKER_SUBMIT_SECRET`` (required; distinct one-way secret used only
  from credential-broker to the browser's narrow Basic Auth capability);
- ``CB_BROKER_SITE_ID`` / ``CB_BROKER_ORIGIN`` / selector env vars for the
  single declared form-login site (``CB_BROKER_USERNAME_SELECTOR`` etc.);
- ``CB_INSTANCE_ID``, ``CB_RELEASE_VERSION``, ``CB_PORT`` (service runtime).

No token, key, or credential survives a request; the process holds only
the vault account password from the environment (in-memory).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping
from urllib.parse import urlsplit

from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport
from cloudbrowser.basic_auth_http import HttpBasicAuthBrowser
from cloudbrowser.credential_broker.adapters.basic import (
    BasicAuthAdapter,
    BasicAuthDeclaration,
)
from cloudbrowser.credential_broker.adapters.form import (
    FormLoginAdapter,
    FormLoginDeclaration,
)
from cloudbrowser.credential_broker.api import (
    AuthenticatedPrincipal,
    BrokerHttpServer,
    ServerIdentity,
)
from cloudbrowser.credential_broker.contracts import LoginIntent
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.security.vault_client import VaultwardenClient
from cloudbrowser.sidecar_form_browser import SidecarFormBrowser

_REQUIRED = ("CB_VAULT_BASE_URL", "CB_VAULT_EMAIL", "CB_VAULT_PASSWORD")
_SELECTORS = (
    ("CB_BROKER_USERNAME_SELECTOR", "username_selector"),
    ("CB_BROKER_PASSWORD_SELECTOR", "password_selector"),
    ("CB_BROKER_SUBMIT_SELECTOR", "submit_selector"),
    ("CB_BROKER_SUCCESS_SELECTOR", "success_selector"),
)


# ---------------------------------------------------------------------------
# Real transport (urllib; injected into VaultwardenClient)
# ---------------------------------------------------------------------------


def make_urllib_transport(base_url: str) -> Callable[..., tuple[int, bytes]]:
    """HTTPS-capable transport with the host pinned to the configured base."""

    def transport(
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, bytes]:
        if not url.startswith(base_url.rstrip("/") + "/"):
            raise ValueError("transport refused a URL outside the configured vault host")
        request = urllib.request.Request(url, data=body, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    return transport


def make_default_browser() -> HttpAgentBrowser:
    """Build the real ``HttpAgentBrowser`` from environment configuration.

    Required: ``CB_BROWSER_API_URL``, ``CB_PRINCIPAL_ID``,
    ``CB_BINDING_GENERATION``. Reads ``CB_BROWSER_API_URL`` (defaults to
    ``http://browser:9230``), uses ``urllib`` JSON for the sidecar
    client. Readiness check happens at adapter-execute time so a cold
    browser does not crash the service.
    """
    from cloudbrowser.browser_slots.http_client import HttpJsonClient

    principal_id = os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned")
    generation = os.environ.get("CB_BINDING_GENERATION", "generation-0")
    api_url = os.environ.get("CB_BROWSER_API_URL", "http://browser:9230")
    transport = HttpAgentBrowserTransport(
        HttpJsonClient(api_url),
        expected_owner=principal_id,
        expected_generation=generation,
    )
    return HttpAgentBrowser(transport)


# Type alias for browser factories used in tests / production injection.
BrowserFactory = Callable[[], HttpAgentBrowser]


# ---------------------------------------------------------------------------
# Principal resolution (shared-secret caller auth → static slot binding)
# ---------------------------------------------------------------------------


class SharedSecretPrincipalResolver:
    """Maps a caller presenting the broker secret to the slot's binding."""

    def __init__(self, *, secret: str, principal: AuthenticatedPrincipal) -> None:
        import secrets as _secrets

        self._compare = _secrets.compare_digest
        self._secret = secret
        self._principal = principal

    def __call__(self, auth_token: str) -> AuthenticatedPrincipal:
        if not self._compare(str(auth_token), self._secret):
            raise PermissionError("invalid broker secret")
        return self._principal


# ---------------------------------------------------------------------------
# Binding resolution (single-slot service: static, generation from env)
# ---------------------------------------------------------------------------


def make_static_binding(principal: AuthenticatedPrincipal) -> Callable[[object], ResolvedBinding]:
    def resolve(_intent: object) -> ResolvedBinding:
        return ResolvedBinding(
            profile_id=principal.profile_id,
            principal_id=principal.principal_id,
            browser_id=principal.browser_id,
            site_id=principal.site_id,
            generation=principal.generation,
        )

    return resolve


# ---------------------------------------------------------------------------
# Server assembly
# ---------------------------------------------------------------------------


def build_broker_api(
    *,
    browser_factory: Callable[[], object] | None = None,
    vault_transport: Callable[..., tuple[int, bytes]] | None = None,
    credential_fetcher: Callable[[str], object] | None = None,
) -> BrokerHttpServer:
    """Assemble the full broker stack from environment configuration.

    ``browser_factory``, ``vault_transport``, and ``credential_fetcher``
    are injection seams for tests; production uses
    ``make_default_browser``, ``make_urllib_transport``, and
    ``VaultwardenClient.fetch``. The vault password lives only in this
    process's environment (never on disk, never logged).
    """
    adapter_kind = os.environ.get("CB_BROKER_ADAPTER", "form").strip().lower()
    if adapter_kind not in {"form", "basic"}:
        raise SystemExit("CB_BROKER_ADAPTER must be 'form' or 'basic'")
    required = list(_REQUIRED)
    if credential_fetcher is not None:
        required = []
    for name in required:
        if not os.environ.get(name):
            raise SystemExit(f"{name} is required")
    if adapter_kind == "form":
        for name, _field in _SELECTORS:
            if not os.environ.get(name):
                raise SystemExit(f"{name} is required")
    elif not os.environ.get("CB_BROKER_SUCCESS_PATH"):
        raise SystemExit("CB_BROKER_SUCCESS_PATH is required for Basic Auth")

    if browser_factory is None:
        browser_factory = make_default_browser
    if credential_fetcher is None and vault_transport is None:
        vault_transport = make_urllib_transport(os.environ["CB_VAULT_BASE_URL"])

    broker_secret = os.environ.get("CB_BROKER_SHARED_SECRET", "")
    if len(broker_secret) < 16:
        raise SystemExit("CB_BROKER_SHARED_SECRET must be at least 16 characters")

    browser_submit_secret = os.environ.get("CB_BROKER_SUBMIT_SECRET", "")
    if len(browser_submit_secret) < 16:
        raise SystemExit("CB_BROKER_SUBMIT_SECRET must be at least 16 characters")

    principal = AuthenticatedPrincipal(
        profile_id=os.environ.get("CB_PROFILE_ID", "profile-unassigned"),
        principal_id=os.environ["CB_PRINCIPAL_ID"],
        browser_id=os.environ["CB_BROWSER_ID"],
        site_id=os.environ["CB_BROKER_SITE_ID"],
        generation=os.environ.get("CB_BINDING_GENERATION", "generation-0"),
    )
    identity = ServerIdentity(
        component="credential-broker",
        instance_id=os.environ.get("CB_INSTANCE_ID", "cloudbroker-broker"),
    )

    site_id = os.environ["CB_BROKER_SITE_ID"]
    origin = os.environ["CB_BROKER_ORIGIN"]
    if adapter_kind == "basic":
        declaration: object = BasicAuthDeclaration(
            site_id=site_id,
            origin=origin,
            success_path=os.environ["CB_BROKER_SUCCESS_PATH"],
        )
    else:
        declaration = FormLoginDeclaration(
            site_id=site_id,
            origin=origin,
            username_selector=os.environ["CB_BROKER_USERNAME_SELECTOR"],
            password_selector=os.environ["CB_BROKER_PASSWORD_SELECTOR"],
            submit_selector=os.environ["CB_BROKER_SUBMIT_SELECTOR"],
            success_selector=os.environ["CB_BROKER_SUCCESS_SELECTOR"],
        )

    if credential_fetcher is None:
        assert vault_transport is not None
        vault = VaultwardenClient(
            base_url=os.environ["CB_VAULT_BASE_URL"],
            email=os.environ["CB_VAULT_EMAIL"],
            password=os.environ["CB_VAULT_PASSWORD"],
            transport=vault_transport,
        )
        credential_fetcher = vault.fetch

    def make_adapter(
        _site_id: str, _declaration: object, intent: LoginIntent
    ) -> Callable[..., object]:
        browser = browser_factory()
        live_binding = getattr(browser, "live_binding", None)
        if not callable(live_binding):
            raise RuntimeError("browser does not expose live binding proof")
        live = live_binding()
        if (
            not isinstance(live, tuple)
            or len(live) != 2
            or not all(isinstance(value, str) for value in live)
        ):
            raise RuntimeError("browser returned invalid live binding proof")
        live_owner, live_generation = live
        if (
            live_owner != intent.principal_id
            or live_generation != intent.binding_generation
        ):
            raise RuntimeError("browser live binding does not match login intent")
        transport = getattr(browser, "transport", None)
        rotate_binding = getattr(transport, "rotate_binding", None)
        if callable(rotate_binding):
            rotate_binding(live_owner, live_generation)
            readiness = getattr(browser, "readiness", None)
            if not callable(readiness):
                raise RuntimeError("browser does not expose readiness proof")
            readiness()
        # Re-read browser ownership immediately before invoking the
        # credential-bearing adapter. This closes reassignment races that can
        # occur after vault retrieval or challenge probing.
        live_before_fill = live_binding()
        if live_before_fill != (intent.principal_id, intent.binding_generation):
            raise RuntimeError("browser binding changed before credential fill")
        if adapter_kind == "basic":
            adapter = BasicAuthAdapter()
            if callable(getattr(browser, "submit_basic_auth", None)):
                # Direct BasicAuthBrowser injection (integration tests and
                # future in-process broker capability).
                basic_browser = browser
            else:
                # Production path: HttpAgentBrowser -> secret-gated internal
                # browser API. The normal agent surface has no Basic methods.
                transport = getattr(browser, "transport", None)
                client_factory = getattr(transport, "client", None)
                if not callable(client_factory):
                    raise RuntimeError("browser does not provide a Basic Auth capability")
                basic_browser = HttpBasicAuthBrowser(
                    client_factory(),
                    shared_secret=browser_submit_secret,
                )
            target_id = intent.target_tab_id
            if not isinstance(target_id, str) or not target_id:
                raise RuntimeError("Basic Auth login requires target_tab_id")
            return lambda declaration, material: adapter.execute(
                declaration,
                material,
                basic_browser,
                target_id=target_id,
            )
        adapter = FormLoginAdapter()
        return lambda declaration, material: adapter.execute(
            declaration, material, SidecarFormBrowser(browser)
        )

    coordinator = BrokerCoordinator(
        resolve_initial=make_static_binding(principal),
        resolve_pre_fill=make_static_binding(principal),
        declarations={site_id: declaration},
        adapter_selector=make_adapter,
        audit_emit=_log_audit_event,
    )

    resolver = SharedSecretPrincipalResolver(secret=broker_secret, principal=principal)

    return BrokerHttpServer(
        server_identity=identity,
        principal_for=resolver,
        coordinator=coordinator,
        fetch_credentials=credential_fetcher,
    )


def _log_audit_event(event_type: object, fields: Mapping[str, object]) -> None:
    """Structured audit to stdout; material redaction is upstream's contract."""
    try:
        print(json.dumps({"event": str(event_type), **dict(fields)}), flush=True)
    except (TypeError, ValueError):
        print(json.dumps({"event": str(event_type)}), flush=True)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 64 * 1024


def create_broker_server(address: tuple[str, int] = ("0.0.0.0", 8080)) -> ThreadingHTTPServer:
    api = build_broker_api()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _send_json(self, status: int, payload: Mapping[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> Mapping[str, object]:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                raise ValueError("content-length is not an integer")
            if length < 0 or length > _MAX_BODY_BYTES:
                raise ValueError("payload too large")
            if length == 0:
                return {}
            decoded = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("request must be an object")
            return decoded

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/health":
                self._send_json(200, {"status": "ok", "component": "credential-broker"})
                return
            self._send_json(404, {"ok": False, "error_code": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path != "/v1/credential/login":
                self._send_json(404, {"ok": False, "error_code": "not_found"})
                return
            try:
                body = self._read_body()
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(
                    400,
                    {"request_id": "missing", "status": "failed", "error_code": "invalid_request"},
                )
                return
            try:
                with api.handle(path, body) as response:
                    self._send_json(200, response.body)
            except LookupError:
                self._send_json(404, {"ok": False, "error_code": "not_found"})

    return ThreadingHTTPServer(address, Handler)


__all__ = ["create_broker_server", "build_broker_api", "make_urllib_transport"]
