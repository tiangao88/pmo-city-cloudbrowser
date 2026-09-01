from dataclasses import dataclass
from pathlib import Path

import pytest

from cloudbrowser.browser_slots.lifecycle import BrowserBinding, OwnerBoundLifecycle
from cloudbrowser.browser_slots.transport import BrowserReadiness, BrowserUnavailable
from cloudbrowser.browser_slots.http_transport import HttpBrowserTransport


BINDING = BrowserBinding("profile-a", "principal-a", "browser-a", "g1")


@dataclass
class FakeHttpClient:
    responses: dict[str, object]

    def __post_init__(self):
        self.calls: list[tuple[str, str | None]] = []

    def request(self, method: str, path: str, *, body: str | None = None) -> object:
        self.calls.append((method, path if body is None else f"{path}:{body}"))
        response = self.responses.get(f"{method} {path}")
        if isinstance(response, BaseException):
            raise response
        return response


def test_http_transport_exposes_only_allowlisted_browser_operations():
    client = FakeHttpClient(
        {
            "POST /browser/start": {"ok": True},
            "POST /browser/stop": {"ok": True},
            "GET /browser/readiness": {
                "owner": "principal-a",
                "generation": "g1",
                "cdp_ok": True,
            },
            "GET /browser/pages": {"urls": ["https://example.test/a"]},
            "POST /browser/pages/open": {"ok": True},
            "POST /browser/pages/close-empty": {"ok": True},
        }
    )
    transport = HttpBrowserTransport(client, expected_owner="principal-a", expected_generation="g1")

    transport.start()
    assert transport.readiness() == BrowserReadiness("principal-a", "g1", True)
    assert transport.list_page_urls() == ["https://example.test/a"]
    transport.open_page("https://example.test/a")
    transport.close_empty_pages()
    transport.stop()

    assert all("cdp" not in path.lower() for _, path in client.calls)
    assert all("cookie" not in path.lower() for _, path in client.calls)


def test_http_transport_rejects_non_matching_readiness():
    client = FakeHttpClient(
        {
            "GET /browser/readiness": {
                "owner": "principal-other",
                "generation": "g2",
                "cdp_ok": True,
            }
        }
    )
    transport = HttpBrowserTransport(client, expected_owner="principal-a", expected_generation="g1")
    with pytest.raises(BrowserUnavailable):
        transport.readiness()


def test_http_transport_rejects_non_http_urls_before_request():
    client = FakeHttpClient({"POST /browser/pages/open": {"ok": True}})
    transport = HttpBrowserTransport(client, expected_owner="principal-a", expected_generation="g1")
    with pytest.raises(ValueError):
        transport.open_page("file:///etc/passwd")
    assert client.calls == []


def test_supervisor_uses_concrete_http_transport(tmp_path: Path):
    client = FakeHttpClient(
        {
            "POST /browser/start": {"ok": True},
            "GET /browser/readiness": {
                "owner": "principal-a",
                "generation": "g1",
                "cdp_ok": True,
            },
            "GET /browser/pages": {"urls": []},
            "POST /browser/pages/close-empty": {"ok": True},
        }
    )
    transport = HttpBrowserTransport(client, expected_owner="principal-a", expected_generation="g1")
    lifecycle = OwnerBoundLifecycle(BINDING, tmp_path / "tabs.json")
    from cloudbrowser.browser_slots.supervisor import SlotSupervisor

    result = SlotSupervisor(lifecycle, transport).wake(BINDING, timeout_s=1, poll_s=0.01)
    assert result.status == "ready"
