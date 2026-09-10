"""The /agent/pages response preserves Chrome's real target metadata."""

from __future__ import annotations

import json
import threading
from urllib.request import urlopen

from cloudbrowser.browser_slots.browser_server import create_browser_server


class _Chrome:
    def json_request(self, path: str, *, method: str = "GET") -> object:
        if path == "/json/list":
            return [
                {
                    "type": "page",
                    "id": "A1B2C3D4",
                    "url": "https://example.test/exact",
                    "title": "Exact title",
                },
                {
                    "type": "service_worker",
                    "id": "ignored",
                    "url": "https://example.test/sw",
                    "title": "ignored",
                },
            ]
        raise AssertionError((method, path))


class _Adapter:
    chrome = _Chrome()

    def readiness(self):
        return type("R", (), {"owner": "owner", "generation": "g1", "cdp_ok": True})()

    def list_page_urls(self):
        return ["https://example.test/exact?x=1"]


class _Process:
    state = "ready"

    def readiness(self):
        return True


def test_agent_pages_uses_exact_chrome_id_url_and_title() -> None:
    server = create_browser_server(
        _Adapter(),
        _Process(),
        instance_id="test",
        release_version="test",
        address=("127.0.0.1", 0),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_address[1]}/agent/pages", timeout=3) as response:
            body = json.loads(response.read())
        assert body == {
            "pages": [
                {
                    "tab_id": "A1B2C3D4",
                    "url": "https://example.test/exact",
                    "title": "Exact title",
                }
            ]
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
