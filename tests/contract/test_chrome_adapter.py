import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cloudbrowser.browser_slots.chrome_adapter import ChromeBrowserAdapter, ChromeHttpClient, create_browser_server
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
                {"type": "page", "url": "https://example.test/a", "id": "tab-a"},
                {"type": "page", "url": "chrome://newtab/", "id": "tab-new"},
                {"type": "service_worker", "url": "https://extension.test/sw", "id": "sw"},
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


def test_chrome_adapter_requires_explicit_process_lifecycle_callbacks():
    client = FakeChromeClient({})
    adapter = ChromeBrowserAdapter(client, owner="principal-a", generation="g1")
    with pytest.raises(BrowserUnavailable):
        adapter.start()
    with pytest.raises(BrowserUnavailable):
        adapter.stop()


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
