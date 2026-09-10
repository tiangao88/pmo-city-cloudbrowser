"""TDD coverage for deadline propagation across broker binding/preflight HTTP seams."""

from __future__ import annotations

import pytest

from cloudbrowser.agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport
from cloudbrowser.credential_broker.contracts import (
    GrantAuthorization,
    LoginIntent,
    SiteDeclaration,
)
from cloudbrowser.credential_broker.coordinator import BrokerCoordinator
from cloudbrowser.credential_broker.deadline import BrokerDeadline, BrokerDeadlineExceeded
from cloudbrowser.credential_broker.runtime import (
    BrowserBindingProvider,
    BrowserTargetPreflight,
    LiveBrowserBinding,
)
from cloudbrowser.credential_broker.service import AdapterResult, ResolvedBinding

_BINDING = ResolvedBinding(
    profile_id="profile-a",
    principal_id="principal-a",
    browser_id="browser-a",
    site_id="site-a",
    generation="generation-a",
)
_INTENT = LoginIntent(
    request_id="request-a",
    profile_id="profile-a",
    principal_id="principal-a",
    browser_id="browser-a",
    site_id="site-a",
    target_tab_id="target-a",
    binding_generation="generation-a",
)
_DECLARATION = SiteDeclaration("site-a", "https://login.example.test")


class _RecordingClient:
    def __init__(self, *, on_request=None) -> None:
        self.timeouts: list[float | None] = []
        self.paths: list[str] = []
        self._on_request = on_request

    def request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> object:
        self.paths.append(path)
        self.timeouts.append(timeout_s)
        if self._on_request is not None:
            self._on_request()
        if path == "/agent/readiness":
            return {
                "profile_id": "profile-a",
                "owner": "principal-a",
                "browser_id": "browser-a",
                "generation": "generation-a",
                "cdp_ok": True,
            }
        if path == "/agent/pages":
            return {
                "pages": [
                    {
                        "tab_id": "target-a",
                        "url": "https://login.example.test/form",
                        "title": "Login",
                    }
                ]
            }
        if path == "/browser/readiness":
            return {"owner": "principal-a", "generation": "generation-a", "cdp_ok": True}
        if path == "/browser/pages":
            return {"urls": ["https://login.example.test/form"]}
        raise AssertionError(path)


def _grant(binding: ResolvedBinding, site_id: str, target_tab_id: str) -> GrantAuthorization:
    return GrantAuthorization(
        username_ref="server-item",
        profile_id=binding.profile_id,
        principal_id=binding.principal_id,
        browser_id=binding.browser_id,
        generation=binding.generation,
        site_id=site_id,
        target_tab_id=target_tab_id,
    )


def test_coordinator_passes_one_deadline_to_binding_and_preflight_resolution() -> None:
    seen: list[tuple[str, object]] = []

    def resolve_initial(intent, *, deadline):  # noqa: ANN001
        seen.append(("initial", deadline))
        return _BINDING

    def resolve_pre_fill(intent, *, deadline):  # noqa: ANN001
        seen.append(("pre-fill", deadline))
        return _BINDING

    def preflight(intent, declaration, *, deadline):  # noqa: ANN001
        seen.append(("preflight", deadline))
        return ("target-a", "https://login.example.test/form")

    def fetch(ref, *, deadline):  # noqa: ANN001
        seen.append(("fetch", deadline))
        return object()

    def select(site_id, declaration, intent, *, deadline):  # noqa: ANN001
        seen.append(("select", deadline))

        def adapter(declaration, material, *, deadline):  # noqa: ANN001
            seen.append(("adapter", deadline))
            return AdapterResult("authenticated", True)

        return adapter

    deadline = BrokerDeadline(100.0, monotonic_clock=lambda: 90.0)
    coordinator = BrokerCoordinator(
        resolve_initial=resolve_initial,
        resolve_pre_fill=resolve_pre_fill,
        declarations={"site-a": _DECLARATION},
        adapter_selector=select,
        grant_resolver=_grant,
        target_preflight=preflight,
    )

    result = coordinator.execute(_INTENT, fetch_credentials=fetch, deadline=deadline)

    assert result.status == "authenticated"
    assert {name for name, _ in seen} >= {"initial", "pre-fill", "preflight"}
    assert all(value is deadline for _, value in seen)


def test_binding_and_exact_target_http_calls_receive_remaining_budget() -> None:
    client = _RecordingClient()
    browser = HttpAgentBrowser(HttpAgentBrowserTransport(client, "principal-a", "generation-a"))
    deadline = BrokerDeadline(12.5, monotonic_clock=lambda: 10.0)

    binding = BrowserBindingProvider(browser_factory=lambda: browser, site_id="site-a").resolve(
        _INTENT, deadline=deadline
    )
    proof = BrowserTargetPreflight(lambda: browser).preflight(
        _INTENT, _DECLARATION, deadline=deadline
    )

    assert binding == _BINDING
    assert proof == ("target-a", "https://login.example.test/form")
    assert client.paths == ["/agent/readiness", "/agent/pages"]
    assert client.timeouts == [pytest.approx(2.5), pytest.approx(2.5)]


def test_binding_resolution_rejects_callback_response_after_deadline() -> None:
    clock = [0.0]

    class Browser:
        def live_binding(self):  # noqa: ANN001
            clock[0] = 2.0
            return LiveBrowserBinding("profile-a", "principal-a", "browser-a", "generation-a")

    deadline = BrokerDeadline(1.0, monotonic_clock=lambda: clock[0])

    with pytest.raises(BrokerDeadlineExceeded):
        BrowserBindingProvider(browser_factory=Browser, site_id="site-a").resolve(
            _INTENT, deadline=deadline
        )


def test_exact_target_preflight_rejects_sidecar_response_after_deadline() -> None:
    clock = [0.0]

    def advance() -> None:
        clock[0] = 2.0

    client = _RecordingClient(on_request=advance)
    browser = HttpAgentBrowser(
        HttpAgentBrowserTransport(client, "principal-a", "generation-a")
    )
    deadline = BrokerDeadline(1.0, monotonic_clock=lambda: clock[0])

    with pytest.raises(BrokerDeadlineExceeded):
        BrowserTargetPreflight(lambda: browser).preflight(
            _INTENT, _DECLARATION, deadline=deadline
        )


def test_binding_factory_receives_shared_deadline() -> None:
    seen: list[object] = []
    deadline = BrokerDeadline(100.0, monotonic_clock=lambda: 90.0)

    class Browser:
        def live_binding(self, *, deadline):  # noqa: ANN001
            seen.append(deadline)
            return LiveBrowserBinding("profile-a", "principal-a", "browser-a", "generation-a")

    def factory(*, deadline: BrokerDeadline) -> Browser:
        seen.append(deadline)
        return Browser()

    binding = BrowserBindingProvider(
        browser_factory=factory,  # type: ignore[arg-type]
        site_id="site-a",
    ).resolve(_INTENT, deadline=deadline)

    assert binding == _BINDING
    assert seen == [deadline, deadline]


def test_agent_http_transport_caps_fixed_timeout_to_remaining_deadline() -> None:
    client = _RecordingClient()
    transport = HttpAgentBrowserTransport(
        client,
        expected_owner="principal-a",
        expected_generation="generation-a",
        request_timeout_s=30.0,
    )
    deadline = BrokerDeadline(10.5, monotonic_clock=lambda: 10.0)

    transport.list_pages(deadline=deadline)

    assert client.timeouts == [pytest.approx(0.5)]


def test_slot_http_transport_caps_fixed_timeout_to_remaining_deadline() -> None:
    client = _RecordingClient()
    transport = HttpBrowserTransport(
        client,
        expected_owner="principal-a",
        expected_generation="generation-a",
    )
    deadline = BrokerDeadline(10.5, monotonic_clock=lambda: 10.0)

    transport.list_page_urls(deadline=deadline)

    assert client.timeouts == [pytest.approx(0.5)]
