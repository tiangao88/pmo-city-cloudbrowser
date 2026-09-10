"""Browser service exact-target SSO startup contracts."""

from __future__ import annotations

import pytest

from cloudbrowser import browser_service
from cloudbrowser.credential_broker.deadline import BrokerDeadline


class RecordingClient:
    def __init__(self) -> None:
        self.timeouts: list[float] = []
        self.headers: list[dict[str, str]] = []

    def request(
        self,
        method,
        path,
        *,
        body=None,
        headers=None,
        timeout_s: float | None = None,
    ):
        assert method == "POST"
        assert timeout_s is not None
        self.timeouts.append(timeout_s)
        self.headers.append(dict(headers or {}))
        if path == "/broker/authentik/state":
            return {"url": "https://auth.example.test/", "modality": None}
        raise AssertionError(path)


def test_authentik_http_uses_remaining_deadline_for_each_request() -> None:
    from cloudbrowser.authentik_http import HttpAuthentikBrowser

    now = [100.0]
    deadline = BrokerDeadline(100.4, monotonic_clock=lambda: now[0])
    client = RecordingClient()
    browser = HttpAuthentikBrowser(
        client,
        "submit-secret-0123456789abcdef",
        "target-1",
        deadline=deadline,
    )

    assert browser.current_url() == "https://auth.example.test/"
    assert client.timeouts == [pytest.approx(0.4)]
    assert client.headers == [
        {
            "X-CB-Broker-Secret": "submit-secret-0123456789abcdef",
            "X-CB-Broker-Deadline-S": "0.400000",
        }
    ]


def test_authentik_http_rejects_expired_deadline_before_transport() -> None:
    from cloudbrowser.authentik_http import HttpAuthentikBrowser
    from cloudbrowser.credential_broker.deadline import BrokerDeadlineExceeded

    client = RecordingClient()
    browser = HttpAuthentikBrowser(
        client,
        "submit-secret-0123456789abcdef",
        "target-1",
        deadline=BrokerDeadline(100.0, monotonic_clock=lambda: 100.0),
    )

    with pytest.raises(BrokerDeadlineExceeded):
        browser.current_url()
    assert client.timeouts == []


def _base(monkeypatch) -> None:
    monkeypatch.setenv("CB_INSTANCE_ID", "test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "sso")


def test_browser_startup_rejects_sso_without_policy(monkeypatch) -> None:
    _base(monkeypatch)
    for name in (
        "CB_BROKER_SSO_IDP_ORIGINS",
        "CB_BROKER_SSO_APPLICATION_ORIGINS",
        "CB_BROKER_SSO_SUCCESS_PATHS",
        "CB_BROKER_SSO_IDENTITY_SELECTOR",
        "CB_BROKER_SSO_IDENTITY_CLAIM",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="CB_BROKER_SSO_IDP_ORIGINS is required"):
        browser_service.build_browser_service()


def test_authentik_http_client_deadline_covers_stage_timeout(monkeypatch) -> None:
    from cloudbrowser.authentik_http import HttpAuthentikBrowser

    class Client:
        _timeout_s = 5.0

        def request(self, method, path, *, body=None, headers=None):
            raise AssertionError((method, path, body, headers))

    monkeypatch.setenv("CB_BROKER_SSO_STAGE_TIMEOUT_S", "20")
    client = Client()
    HttpAuthentikBrowser(client, "submit-secret-0123456789abcdef", "target-1")
    assert client._timeout_s == 20.5


def test_authentik_http_client_deadline_is_capped_by_end_to_end_deadline(monkeypatch) -> None:
    from cloudbrowser.authentik_http import HttpAuthentikBrowser

    class Client:
        _timeout_s = 45.0

        def request(self, method, path, *, body=None, headers=None):
            raise AssertionError((method, path, body, headers))

    monkeypatch.setenv("CB_BROKER_SSO_STAGE_TIMEOUT_S", "30")
    client = Client()
    HttpAuthentikBrowser(client, "submit-secret-0123456789abcdef", "target-1")
    assert client._timeout_s == 30.0
