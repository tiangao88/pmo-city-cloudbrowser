"""Server-authoritative binding and broker runtime assembly."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, cast
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from cloudbrowser.authentik_http import AuthentikClient
    from cloudbrowser.basic_auth_http import BasicAuthClient

from cloudbrowser.browser_slots.transport import BrowserUnavailable
from cloudbrowser.credential_broker.adapters.basic import (
    BasicAuthAdapter,
    BasicAuthBrowser,
    BasicAuthDeclaration,
)
from cloudbrowser.credential_broker.adapters.form import CredentialMaterial
from cloudbrowser.credential_broker.adapters.sso import (
    AuthentikBrowser,
    AuthentikSSOAdapter,
    AuthentikSSODeclaration,
)
from cloudbrowser.credential_broker.api import (
    BindingProvider,
    BrokerHttpServer,
    ServerIdentity,
)
from cloudbrowser.credential_broker.contracts import LoginIntent
from cloudbrowser.credential_broker.coordinator import AuthorizationGate, BrokerCoordinator
from cloudbrowser.credential_broker.deadline import BrokerDeadline, invoke_with_deadline
from cloudbrowser.credential_broker.grant_custody import (
    CustodyCredentialFetcher,
    CustodyGrantStore,
    parse_kek,
)
from cloudbrowser.credential_broker.idempotency import DurableIdempotencyStore
from cloudbrowser.credential_broker.nonce_store import DurableNonceStore
from cloudbrowser.credential_broker.service import (
    AdapterResult,
    DependencyUnavailable,
    GrantResolver,
    ResolvedBinding,
    TargetPreflight,
)
from cloudbrowser.credential_capability import CapabilityCodec
from cloudbrowser.security.policy import parse_authentik_policy, validate_deadline_policy

_REQUIRED = ("CB_VAULT_BASE_URL", "CB_BROKER_GRANT_KEK_HEX")
_SELECTORS = (
    "CB_BROKER_USERNAME_SELECTOR",
    "CB_BROKER_PASSWORD_SELECTOR",
    "CB_BROKER_SUBMIT_SELECTOR",
    "CB_BROKER_SUCCESS_SELECTOR",
)
_MAX_BINDING_FIELD = 256


class LiveBindingProvider(Protocol):
    def resolve(
        self,
        intent: LoginIntent,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> ResolvedBinding: ...


@dataclass(frozen=True)
class LiveBrowserBinding:
    profile_id: str
    principal_id: str
    browser_id: str
    generation: str


class BrowserBindingProvider:
    """Resolve the live server-owned binding from the broker browser."""

    def __init__(self, *, browser_factory: Callable[[], object], site_id: str) -> None:
        self._browser_factory = browser_factory
        self._site_id = _required_binding_text(site_id, "site_id")

    def resolve(
        self,
        intent: LoginIntent,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> ResolvedBinding:
        if deadline is not None:
            deadline.check()
        if intent.site_id != self._site_id:
            raise ValueError("site binding is not configured")
        browser = invoke_with_deadline(
            self._browser_factory,
            deadline=deadline,
        )
        live_binding = getattr(browser, "live_binding", None)
        if not callable(live_binding):
            raise BrowserUnavailable("browser live binding is unavailable")
        observed = invoke_with_deadline(live_binding, deadline=deadline)
        if not isinstance(observed, LiveBrowserBinding):
            raise BrowserUnavailable("browser live binding is unavailable")
        if deadline is not None:
            deadline.check()
        return ResolvedBinding(
            profile_id=_required_binding_text(observed.profile_id, "profile_id"),
            principal_id=_required_binding_text(observed.principal_id, "principal_id"),
            browser_id=_required_binding_text(observed.browser_id, "browser_id"),
            site_id=self._site_id,
            generation=_required_binding_text(observed.generation, "generation"),
        )


def _required_binding_text(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > _MAX_BINDING_FIELD
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
    ):
        raise ValueError(f"{name} is invalid")
    return value


def validate_grant_db_path(path: str | os.PathLike[str]) -> Path:
    """Require the versioned custody filename and reject the prior path."""
    candidate = Path(path)
    if candidate.name in {"grants.sqlite3", "grants.sqlite", "grants.db"}:
        raise ValueError(
            "prior grant DB path is forbidden; use /data/state/grant-custody-v1.sqlite3"
        )
    if candidate.name != "grant-custody-v1.sqlite3":
        raise ValueError("grant DB path must end in grant-custody-v1.sqlite3")
    return candidate


def make_urllib_transport(
    base_url: str,
) -> Callable[..., tuple[int, bytes]]:
    """Return a vault transport pinned to the configured base URL."""

    def transport(
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_s: float = 30.0,
    ) -> tuple[int, bytes]:
        if not url.startswith(base_url.rstrip("/") + "/"):
            raise ValueError("transport refused a URL outside the configured vault host")
        request = urllib.request.Request(url, data=body, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DependencyUnavailable("vault dependency is unavailable") from exc

    return transport


def make_default_browser() -> object:
    from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport
    from cloudbrowser.browser_slots.http_client import HttpJsonClient

    api_url = os.environ.get("CB_BROWSER_API_URL", "http://browser:9230")
    client = HttpJsonClient(api_url)
    transport = HttpAgentBrowserTransport(
        client,
        expected_owner=os.environ.get("CB_PRINCIPAL_ID", "principal-unassigned"),
        expected_generation=os.environ.get("CB_BINDING_GENERATION", "generation-0"),
    )
    return HttpAgentBrowser(transport)


class ProductionGrantResolver(CustodyGrantStore):
    """Runtime resolver backed by the per-user two-leg custody store."""


class BrowserTargetPreflight:
    """Probe the actual target and require the declared origin."""

    def __init__(self, browser_factory: Callable[[], object]) -> None:
        self._browser_factory = browser_factory

    def preflight(
        self,
        intent: LoginIntent,
        declaration: object,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> object:
        target_id = intent.target_tab_id
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("target_tab_id is required")
        browser = invoke_with_deadline(
            self._browser_factory,
            deadline=deadline,
        )
        current_url = getattr(browser, "current_url", None)
        if callable(current_url):
            try:
                observed_url = invoke_with_deadline(
                    current_url,
                    target_id=target_id,
                    deadline=deadline,
                )
            except TypeError as exc:
                if "target_id" not in str(exc):
                    raise
                raise ValueError("browser current_url is not target-scoped") from exc
        else:
            list_pages = getattr(browser, "list_pages", None)
            if not callable(list_pages):
                raise ValueError("browser does not expose exact-target state")
            pages = invoke_with_deadline(list_pages, deadline=deadline)
            if not isinstance(pages, list):
                raise ValueError("browser returned invalid target state")
            matches = [
                page for page in pages
                if isinstance(page, dict) and page.get("tab_id") == target_id
            ]
            if len(matches) != 1 or not isinstance(matches[0].get("url"), str):
                raise ValueError("exact target does not exist")
            observed_url = matches[0]["url"]
        if not isinstance(observed_url, str):
            raise ValueError("browser returned invalid target URL")
        allows = getattr(declaration, "allows", None)
        if not callable(allows) or not allows(observed_url):
            raise ValueError("actual target origin is not declared")
        if deadline is not None:
            deadline.check()
        return (target_id, observed_url)


def make_runtime_adapter(
    *,
    adapter_kind: str,
    browser: object,
    browser_submit_secret: str,
    intent: LoginIntent,
    deadline: BrokerDeadline | None = None,
) -> Callable[[object, object], AdapterResult]:
    """Build a per-request adapter around an exact-target browser capability."""

    if adapter_kind == "sso":
        if not isinstance(intent.target_tab_id, str) or not intent.target_tab_id:
            raise BrowserUnavailable("browser Authentik target is unavailable")
        adapter = AuthentikSSOAdapter()
        required = (
            "current_url",
            "begin_authentik",
            "identification",
            "mfa_stage",
            "application_identity",
        )
        if all(callable(getattr(browser, name, None)) for name in required):
            capability = cast(AuthentikBrowser, browser)
        else:
            transport = getattr(browser, "transport", None)
            client = getattr(transport, "client", None)
            if client is None:
                raise BrowserUnavailable("browser Authentik capability is unavailable")
            from cloudbrowser.authentik_http import HttpAuthentikBrowser

            capability = cast(
                AuthentikBrowser,
                HttpAuthentikBrowser(
                    cast("AuthentikClient", client),
                    browser_submit_secret,
                    intent.target_tab_id,
                    deadline=deadline,
                ),
            )

        def execute_sso(
            declaration: object,
            material: object,
            *,
            browser: AuthentikBrowser,
            deadline: BrokerDeadline | None = None,
        ) -> AdapterResult:
            credentials = cast(CredentialMaterial, material)
            return adapter.execute(
                cast(AuthentikSSODeclaration, declaration),
                credentials,
                browser,
                expected_account=credentials.username,
                deadline=deadline,
            )

        return partial(execute_sso, browser=capability)

    if adapter_kind == "basic":
        adapter = BasicAuthAdapter()
        if callable(getattr(browser, "submit_basic_auth", None)):
            basic_browser = cast(BasicAuthBrowser, browser)
        else:
            transport = getattr(browser, "transport", None)
            client = getattr(transport, "client", None)
            if client is None:
                raise BrowserUnavailable("browser Basic Auth capability is unavailable")
            from cloudbrowser.basic_auth_http import HttpBasicAuthBrowser

            basic_browser = HttpBasicAuthBrowser(
                cast("BasicAuthClient", client),
                shared_secret=browser_submit_secret,
                deadline=deadline,
            )
        target_id = intent.target_tab_id
        if not isinstance(target_id, str) or not target_id:
            raise BrowserUnavailable("Basic Auth target is unavailable")

        def execute_basic(
            declaration: object,
            material: object,
            *,
            deadline: BrokerDeadline | None = None,
        ) -> AdapterResult:
            return adapter.execute(
                cast(BasicAuthDeclaration, declaration),
                cast(CredentialMaterial, material),
                basic_browser,
                target_id=target_id,
                deadline=deadline,
            )

        return execute_basic

    raise BrowserUnavailable("secure runtime adapter is unavailable")


def build_broker_api(
    *,
    browser_factory: Callable[[], object] | None = None,
    vault_transport: Callable[..., tuple[int, bytes]] | None = None,
    credential_fetcher: Callable[[str], object] | None = None,
    binding_provider: BindingProvider | None = None,
    grant_resolver: object | None = None,
    target_preflight: object | None = None,
    nonce_store: DurableNonceStore | None = None,
    idempotency_store: DurableIdempotencyStore | None = None,
    clock: Callable[[], int | float] = time.time,
    monotonic_clock: Callable[[], float] = time.monotonic,
    outer_timeout_s: float = 30.0,
) -> BrokerHttpServer:
    adapter_kind = os.environ.get("CB_BROKER_ADAPTER", "").strip().lower()
    if adapter_kind == "form":
        raise SystemExit(
            "CB_BROKER_ADAPTER=form is disabled: no broker-only exact-target form capability"
        )
    if adapter_kind not in {"basic", "sso"}:
        raise SystemExit("CB_BROKER_ADAPTER must be 'basic' or 'sso'")
    required = [] if credential_fetcher is not None else list(_REQUIRED)
    for name in required:
        if not os.environ.get(name):
            raise SystemExit(f"{name} is required")
    if adapter_kind == "form":
        for name in _SELECTORS:
            if not os.environ.get(name):
                raise SystemExit(f"{name} is required")
    elif adapter_kind == "basic":
        if not os.environ.get("CB_BROKER_SUCCESS_PATH"):
            raise SystemExit("CB_BROKER_SUCCESS_PATH is required for Basic Auth")
    else:
        for name in (
            "CB_BROKER_SSO_ENTRY_URL",
            "CB_BROKER_SSO_IDP_ORIGINS",
            "CB_BROKER_SSO_CALLBACK_ORIGINS",
            "CB_BROKER_SSO_APPLICATION_ORIGINS",
            "CB_BROKER_SSO_SUCCESS_PATHS",
        ):
            if not os.environ.get(name):
                raise SystemExit(f"{name} is required for SSO")

    if browser_factory is None:
        browser_factory = make_default_browser
    if credential_fetcher is None and vault_transport is None:
        vault_transport = make_urllib_transport(os.environ["CB_VAULT_BASE_URL"])
    capability_secret = os.environ.get("CB_CREDENTIAL_CAPABILITY_SECRET", "")
    if len(capability_secret.encode("utf-8")) < 16:
        raise SystemExit("CB_CREDENTIAL_CAPABILITY_SECRET must be at least 16 bytes")
    capability_audience = os.environ.get("CB_CREDENTIAL_BROKER_AUDIENCE", "")
    if not capability_audience:
        raise SystemExit("CB_CREDENTIAL_BROKER_AUDIENCE is required")
    deployment = os.environ.get("CB_DEPLOYMENT", "") or os.environ.get("CB_INSTANCE_ID", "")
    if not deployment:
        raise SystemExit("CB_DEPLOYMENT or CB_INSTANCE_ID is required")
    browser_submit_secret = os.environ.get("CB_BROKER_SUBMIT_SECRET", "")
    if len(browser_submit_secret) < 16:
        raise SystemExit("CB_BROKER_SUBMIT_SECRET must be at least 16 characters")

    site_id = os.environ["CB_BROKER_SITE_ID"]
    policy = parse_authentik_policy(os.environ)
    if policy is not None:
        try:
            validate_deadline_policy(
                ttl_s=float(os.environ.get("CB_CREDENTIAL_CAPABILITY_TTL_S", "31")),
                outer_timeout_s=float(os.environ.get("CB_CREDENTIAL_BROKER_TIMEOUT_S", "30")),
                stage_timeout_s=policy.stage_timeout_s,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    if binding_provider is None:
        binding_provider = BrowserBindingProvider(browser_factory=browser_factory, site_id=site_id)
    resolve_initial = binding_provider.resolve
    resolve_pre_fill = binding_provider.resolve
    if grant_resolver is None:
        if os.environ.get("CB_BROKER_GRANT_USERNAME_REF"):
            raise SystemExit(
                "CB_BROKER_GRANT_USERNAME_REF is forbidden; use the principal-scoped grant DB"
            )
        grant_path = os.environ.get("CB_BROKER_GRANT_DB_PATH", "")
        if not grant_path:
            raise SystemExit("CB_BROKER_GRANT_DB_PATH is required")
        try:
            grant_path = str(validate_grant_db_path(grant_path))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        kek_text = os.environ.get("CB_BROKER_GRANT_KEK_HEX", "")
        if not kek_text:
            raise SystemExit("CB_BROKER_GRANT_KEK_HEX is required")
        try:
            grant_kek = parse_kek(kek_text)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        grant_resolver = ProductionGrantResolver(grant_path, kek=grant_kek)
    if target_preflight is None:
        target_preflight = BrowserTargetPreflight(browser_factory)
    if nonce_store is None:
        nonce_path = os.environ.get(
            "CB_CREDENTIAL_NONCE_DB_PATH", "/data/state/credential-capability-nonces.sqlite3"
        )
        max_records_raw = os.environ.get("CB_CREDENTIAL_NONCE_MAX_RECORDS", "100000")
        try:
            max_records = int(max_records_raw)
        except ValueError as exc:
            raise SystemExit("CB_CREDENTIAL_NONCE_MAX_RECORDS must be an integer") from exc
        nonce_store = DurableNonceStore(nonce_path, max_records=max_records)
    if idempotency_store is None:
        idempotency_path = os.environ.get("CB_BROKER_IDEMPOTENCY_DB_PATH", "")
        if not idempotency_path:
            raise SystemExit("CB_BROKER_IDEMPOTENCY_DB_PATH is required")
        idempotency_store = DurableIdempotencyStore(idempotency_path)
    identity = ServerIdentity(
        component="credential-broker",
        instance_id=deployment,
    )
    origin = os.environ["CB_BROKER_ORIGIN"]
    if adapter_kind == "basic":
        declaration: object = BasicAuthDeclaration(
            site_id=site_id,
            origin=origin,
            success_path=os.environ["CB_BROKER_SUCCESS_PATH"],
        )
    elif adapter_kind == "sso":
        def csv(name: str) -> tuple[str, ...]:
            return tuple(
                item.strip() for item in os.environ[name].split(",") if item.strip()
            )

        declaration = AuthentikSSODeclaration(
            site_id=site_id,
            entry_url=(
                policy.entry_url
                if policy is not None
                else os.environ["CB_BROKER_SSO_ENTRY_URL"]
            ),
            idp_origins=(
                policy.idp_origins
                if policy is not None
                else csv("CB_BROKER_SSO_IDP_ORIGINS")
            ),
            callback_origins=(
                policy.callback_origins
                if policy is not None
                else csv("CB_BROKER_SSO_CALLBACK_ORIGINS")
            ),
            application_origins=(
                policy.application_origins
                if policy is not None
                else csv("CB_BROKER_SSO_APPLICATION_ORIGINS")
            ),
            application_success_paths=(
                policy.success_paths
                if policy is not None
                else csv("CB_BROKER_SSO_SUCCESS_PATHS")
            ),
            allowed_mfa=(
                policy.allowed_mfa
                if policy is not None
                else tuple(
                    item.strip()
                    for item in os.environ.get(
                        "CB_BROKER_SSO_ALLOWED_MFA", "totp"
                    ).split(",")
                    if item.strip()
                )
            ),
            stage_timeout_s=(
                policy.stage_timeout_s
                if policy is not None
                else float(os.environ.get("CB_BROKER_SSO_STAGE_TIMEOUT_S", "30"))
            ),
            application_identity_selector=(
                policy.identity_selector
                if policy is not None
                else os.environ.get("CB_BROKER_SSO_IDENTITY_SELECTOR", "")
            ),
            application_identity_claim=(
                policy.identity_claim
                if policy is not None
                else os.environ.get("CB_BROKER_SSO_IDENTITY_CLAIM", "")
            ),
        )
    else:
        raise AssertionError("form adapter passed startup fail-closed guard")

    if credential_fetcher is None:
        assert vault_transport is not None
        credential_fetcher = CustodyCredentialFetcher(
            store=cast(CustodyGrantStore, grant_resolver),
            base_url=os.environ["CB_VAULT_BASE_URL"],
            transport=vault_transport,
        )

    def make_adapter(
        _site_id: str,
        _declaration: object,
        intent: LoginIntent,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> Callable[[object, object], AdapterResult]:
        browser = browser_factory()
        live_binding = getattr(browser, "live_binding", None)
        if not callable(live_binding):
            raise BrowserUnavailable("browser live binding is unavailable")
        live = live_binding()
        if (
            not isinstance(live, LiveBrowserBinding)
            or live.profile_id != intent.profile_id
            or live.principal_id != intent.principal_id
            or live.browser_id != intent.browser_id
            or live.generation != intent.binding_generation
        ):
            raise BrowserUnavailable("browser live binding does not match login intent")
        transport = getattr(browser, "transport", None)
        rotate_binding = getattr(transport, "rotate_binding", None)
        if callable(rotate_binding):
            rotate_binding(live.principal_id, live.generation)
            readiness = getattr(browser, "readiness", None)
            if not callable(readiness):
                raise BrowserUnavailable("browser readiness is unavailable")
            readiness()
        live_before_fill = live_binding()
        if (
            not isinstance(live_before_fill, LiveBrowserBinding)
            or live_before_fill != live
        ):
            raise BrowserUnavailable("browser binding changed before credential fill")
        return make_runtime_adapter(
            adapter_kind=adapter_kind,
            browser=browser,
            browser_submit_secret=browser_submit_secret,
            intent=intent,
            deadline=deadline,
        )

    coordinator = BrokerCoordinator(
        resolve_initial=resolve_initial,
        resolve_pre_fill=resolve_pre_fill,
        declarations={site_id: declaration},
        adapter_selector=make_adapter,
        grant_resolver=cast(GrantResolver, grant_resolver),
        target_preflight=cast(TargetPreflight, target_preflight),
        authorization_gate=cast(AuthorizationGate, credential_fetcher)
        if callable(getattr(credential_fetcher, "run_authorized", None))
        else cast(AuthorizationGate, grant_resolver)
        if callable(getattr(grant_resolver, "run_authorized", None))
        else None,
        audit_emit=_log_audit_event,
    )
    return BrokerHttpServer(
        server_identity=identity,
        capability_codec=CapabilityCodec(capability_secret),
        capability_audience=capability_audience,
        deployment=deployment,
        nonce_store=nonce_store,
        idempotency_store=idempotency_store,
        coordinator=coordinator,
        fetch_credentials=credential_fetcher,
        clock=clock,
        monotonic_clock=monotonic_clock,
        outer_timeout_s=outer_timeout_s,
    )


def _log_audit_event(event_type: object, fields: Mapping[str, object]) -> None:
    try:
        print(json.dumps({"event": str(event_type), **dict(fields)}), flush=True)
    except (TypeError, ValueError):
        print(json.dumps({"event": str(event_type)}), flush=True)


_MAX_BODY_BYTES = 64 * 1024


def create_broker_http_server(
    api: BrokerHttpServer,
    address: tuple[str, int] = ("0.0.0.0", 8080),
):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
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
            except ValueError as exc:
                raise ValueError("content-length is not an integer") from exc
            if length < 0 or length > _MAX_BODY_BYTES:
                raise ValueError("payload too large")
            if length == 0:
                return {}
            decoded = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("request must be an object")
            return decoded

        def do_GET(self) -> None:
            if urlsplit(self.path).path == "/health":
                self._send_json(200, {"status": "ok", "component": "credential-broker"})
                return
            self._send_json(404, {"ok": False, "error_code": "not_found"})

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path != "/v1/credential/login":
                self._send_json(404, {"ok": False, "error_code": "not_found"})
                return
            try:
                body = self._read_body()
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(
                    200,
                    {
                        "request_id": "missing",
                        "status": "failed",
                        "error_code": "invalid_request",
                        "duration_ms": 0,
                    },
                )
                return
            try:
                with api.handle(path, body) as response:
                    self._send_json(200, response.body)
            except LookupError:
                self._send_json(404, {"ok": False, "error_code": "not_found"})
            except Exception:
                self._send_json(
                    200,
                    {
                        "request_id": "missing",
                        "status": "failed",
                        "error_code": "internal_error",
                        "duration_ms": 0,
                    },
                )

    return ThreadingHTTPServer(address, Handler)


def create_broker_server(address: tuple[str, int] = ("0.0.0.0", 8080)):
    return create_broker_http_server(build_broker_api(), address)


__all__ = [
    "BrowserBindingProvider",
    "BrowserTargetPreflight",
    "LiveBrowserBinding",
    "LiveBindingProvider",
    "ProductionGrantResolver",
    "build_broker_api",
    "create_broker_http_server",
    "create_broker_server",
    "make_default_browser",
    "make_runtime_adapter",
    "make_urllib_transport",
    "validate_grant_db_path",
]
