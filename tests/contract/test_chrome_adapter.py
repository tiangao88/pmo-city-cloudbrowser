import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.browser_slots.browser_server import create_browser_server as create_deployed_browser_server
from cloudbrowser.browser_slots.browser_process import chrome_version_is_ready
from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter, ChromeHttpClient, create_browser_server
from cloudbrowser.browser_slots.http_client import HttpJsonClient
from cloudbrowser.browser_slots.transport import BrowserUnavailable


class FakeChromeClient:
    def __init__(self, responses: dict[tuple[str, str], object]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def json_request(self, path: str, *, method: str = "GET") -> object:
        self.calls.append((method, path))
        response = self.responses[(method, path)]
        if isinstance(response, BaseException):
            raise response
        return response

    def text_request(self, path: str, *, method: str = "GET") -> str:
        self.calls.append((method, path))
        response = self.responses[(method, path)]
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, str)
        return response


def test_chrome_adapter_reads_only_http_pages_and_closes_blank_targets():
    client = FakeChromeClient(
        {
            ("GET", "/json/version"): {"Browser": "Chrome/128"},
            ("GET", "/json/list"): [
                {
                    "type": "page",
                    "url": "https://example.test/a",
                    "title": "Example A",
                    "id": "tab-a",
                },
                {
                    "type": "page",
                    "url": "chrome://newtab/",
                    "title": "New Tab",
                    "id": "tab-new",
                },
                {
                    "type": "service_worker",
                    "url": "https://extension.test/sw",
                    "id": "sw",
                },
            ],
            ("PUT", "/json/new?https%3A%2F%2Fexample.test%2Fb"): {"id": "tab-b"},
            ("GET", "/json/close/tab-new"): "Closed",
        }
    )
    adapter = ChromeBrowserAdapter(client, owner="principal-a", generation="g1")

    assert adapter.readiness().cdp_ok is True
    assert adapter.list_page_urls() == ["https://example.test/a"]
    adapter.open_page("https://example.test/b")
    adapter.close_empty_pages()
    assert ("PUT", "/json/new?https%3A%2F%2Fexample.test%2Fb") in client.calls
    assert ("GET", "/json/close/tab-new") in client.calls


def test_chrome_adapter_rejects_non_http_page_urls_without_request():
    client = FakeChromeClient({})
    adapter = ChromeBrowserAdapter(client, owner="principal-a", generation="g1")
    with pytest.raises(ValueError):
        adapter.open_page("file:///etc/passwd")
    assert client.calls == []


@pytest.mark.parametrize(
    "base_url",
    (
        "http://192.0.2.1:9222",
        "http://user:password@127.0.0.1:9222",
        "http://:password@127.0.0.1:9222",
        "http://127.0.0.1:9222/json",
        "http://127.0.0.1:9222/?query=secret",
        "http://127.0.0.1:9222/#fragment",
        "http://127.0.0.1:not-a-port",
        "http://127.0.0.1:0",
    ),
)
def test_chrome_http_client_requires_a_bounded_local_origin(base_url: str) -> None:
    with pytest.raises(ValueError):
        ChromeHttpClient(base_url)


def test_chrome_http_client_accepts_loopback_origins() -> None:
    for base_url in (
        "http://127.0.0.1:9222",
        "http://localhost/",
        "https://[::1]:9222",
    ):
        ChromeHttpClient(base_url)


def test_chrome_version_readiness_requires_the_same_local_websocket_contract() -> None:
    valid = {
        "Browser": "Chrome/128",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/1",
    }
    assert chrome_version_is_ready(valid) is True
    for websocket in (
        "ws://192.0.2.1:9222/devtools/browser/1",
        "ws://user:password@127.0.0.1:9222/devtools/browser/1",
        "ws://127.0.0.1/devtools/browser/1",
        "ws://127.0.0.1:not-a-port/devtools/browser/1",
        "wss://127.0.0.1:9222/devtools/browser/1",
        "ws://127.0.0.1:9222/devtools/browser/1#fragment",
    ):
        assert chrome_version_is_ready({**valid, "webSocketDebuggerUrl": websocket}) is False


def test_chrome_adapter_requires_explicit_process_lifecycle_callbacks():
    client = FakeChromeClient({})
    adapter = ChromeBrowserAdapter(client, owner="principal-a", generation="g1")
    with pytest.raises(BrowserUnavailable):
        adapter.start()
    with pytest.raises(BrowserUnavailable):
        adapter.stop()


def test_browser_server_serializes_concurrent_start_and_stop() -> None:
    start_entered = threading.Event()
    release_start = threading.Event()
    stop_entered = threading.Event()

    class Process:
        state = "stopped"

        def readiness(self) -> bool:
            return self.state == "ready"

        def start(self) -> bool:
            self.state = "starting"
            start_entered.set()
            assert release_start.wait(2)
            self.state = "ready"
            return True

        def stop(self) -> None:
            stop_entered.set()
            self.state = "stopped"

    process = Process()
    adapter = ChromeBrowserAdapter(
        FakeChromeClient({}),
        owner="principal-a",
        generation="g1",
        start_callback=process.start,
        stop_callback=process.stop,
    )
    server = create_deployed_browser_server(
        adapter,
        process,  # type: ignore[arg-type]
        instance_id="test-instance",
        release_version="test-release",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    outcomes: dict[str, object] = {}

    def request(name: str, path: str) -> None:
        outcomes[name] = HttpJsonClient(base_url, timeout_s=3).request("POST", path)

    starter = threading.Thread(target=request, args=("start", "/browser/start"))
    stopper = threading.Thread(target=request, args=("stop", "/browser/stop"))
    try:
        starter.start()
        assert start_entered.wait(1)
        stopper.start()
        assert not stop_entered.wait(0.1)
        release_start.set()
        starter.join(2)
        assert stop_entered.wait(1)
        stopper.join(2)
        assert not starter.is_alive()
        assert not stopper.is_alive()
        assert outcomes == {"start": {"ok": True}, "stop": {"ok": True}}
        assert process.state == "stopped"
    finally:
        release_start.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_http_server_page_info_round_trips_through_deployed_client() -> None:
    class PageActions:
        def page_info(self, target_tab_id: str, selector: str | None = None) -> dict[str, str]:
            assert target_tab_id == "tab-1"
            assert selector == "main [role=article]"
            return {
                "url": "https://example.test/page",
                "title": "Example",
                "text": "Selected content",
            }

    client = FakeChromeClient({("GET", "/json/version"): {"Browser": "Chrome/128"}})
    adapter = ChromeBrowserAdapter(
        client,
        owner="principal-a",
        generation="g1",
        page_actions=PageActions(),
    )

    class Process:
        state = "ready"

        @staticmethod
        def readiness() -> bool:
            return True

        @staticmethod
        def stop() -> None:
            return None

    server = create_deployed_browser_server(
        adapter,
        Process(),  # type: ignore[arg-type]
        instance_id="test-instance",
        release_version="test-release",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        http = HttpJsonClient(
            f"http://127.0.0.1:{server.server_address[1]}", timeout_s=2
        )
        assert http.request(
            "GET",
            "/agent/pages/info?target_tab_id=tab-1&selector=main%20%5Brole%3Darticle%5D",
            headers={"X-CB-Principal": "principal-a", "X-CB-Generation": "g1"},
        ) == {
            "url": "https://example.test/page",
            "title": "Example",
            "text": "Selected content",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_http_server_exposes_bounded_routes():
    client = FakeChromeClient(
        {
            ("GET", "/json/version"): {"Browser": "Chrome/128"},
            ("GET", "/json/list"): [],
        }
    )
    adapter = ChromeBrowserAdapter(client, owner="principal-a", generation="g1")
    server = create_browser_server(adapter, address=("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with __import__("urllib.request", fromlist=["urlopen"]).urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/browser/readiness", timeout=2
        ) as response:
            assert response.status == 200
            assert json.load(response) == {"owner": "principal-a", "generation": "g1", "cdp_ok": True}
        with pytest.raises(__import__("urllib.error", fromlist=["HTTPError"]).HTTPError) as error:
            __import__("urllib.request", fromlist=["urlopen"]).urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/raw-cdp", timeout=2
            )
        assert error.value.code == 404
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
