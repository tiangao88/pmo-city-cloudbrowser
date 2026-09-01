"""Browser-side HTTP API backed by a restricted Chrome DevTools adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .transport import BrowserReadiness, BrowserUnavailable


class ChromeHttpClientProtocol(Protocol):
    def json_request(self, path: str, *, method: str = "GET") -> object: ...

    def text_request(self, path: str, *, method: str = "GET") -> str: ...


class ChromeHttpClient:
    """Small stdlib client for the local Chrome HTTP JSON endpoints."""

    def __init__(self, base_url: str = "http://127.0.0.1:9222", *, timeout_s: float = 5.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise ValueError("base_url must be an HTTP(S) origin without userinfo")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an origin")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_s = timeout_s

    def json_request(self, path: str, *, method: str = "GET") -> object:
        return self._request(path, method=method, expect_json=True)

    def text_request(self, path: str, *, method: str = "GET") -> str:
        result = self._request(path, method=method, expect_json=False)
        assert isinstance(result, str)
        return result

    def _request(self, path: str, *, method: str, expect_json: bool) -> object:
        if method not in {"GET", "PUT"}:
            raise ValueError("method is not allowed")
        parsed = urlsplit(path)
        if not path.startswith("/") or parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError("path must be relative to Chrome")
        request = Request(self._base_url + path, method=method)
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                if response.status < 200 or response.status >= 300:
                    raise BrowserUnavailable("Chrome returned a non-success status")
                raw = response.read(128 * 1024)
                content_type = response.headers.get_content_type()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise BrowserUnavailable("Chrome is unavailable") from exc
        if expect_json:
            if content_type != "application/json":
                raise BrowserUnavailable("Chrome returned a non-JSON response")
            try:
                return json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BrowserUnavailable("Chrome returned invalid JSON") from exc
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BrowserUnavailable("Chrome returned invalid text") from exc


@dataclass
class ChromeBrowserAdapter:
    """Expose only lifecycle/page operations required by BrowserTransport."""

    chrome: ChromeHttpClientProtocol
    owner: str
    generation: str
    start_callback: Callable[[], None] | None = None
    stop_callback: Callable[[], None] | None = None

    def start(self) -> None:
        if self.start_callback is None:
            raise BrowserUnavailable("browser start is not configured")
        try:
            self.start_callback()
        except Exception as exc:
            raise BrowserUnavailable("browser start failed") from exc

    def stop(self) -> None:
        if self.stop_callback is None:
            raise BrowserUnavailable("browser stop is not configured")
        try:
            self.stop_callback()
        except Exception as exc:
            raise BrowserUnavailable("browser stop failed") from exc

    def readiness(self) -> BrowserReadiness:
        raw = self.chrome.json_request("/json/version")
        if not isinstance(raw, dict):
            raise BrowserUnavailable("invalid Chrome version response")
        browser = raw.get("Browser")
        if not isinstance(browser, str) or not browser:
            raise BrowserUnavailable("Chrome identity is unavailable")
        return BrowserReadiness(self.owner, self.generation, True)

    def list_page_urls(self) -> list[str]:
        raw = self.chrome.json_request("/json/list")
        if not isinstance(raw, list):
            raise BrowserUnavailable("invalid Chrome target response")
        urls: list[str] = []
        for target in raw:
            if not isinstance(target, dict) or target.get("type") != "page":
                continue
            url = target.get("url")
            if isinstance(url, str) and self._is_page_url(url):
                urls.append(url)
        return urls

    def open_page(self, url: str) -> None:
        if not self._is_page_url(url):
            raise ValueError("only absolute HTTP(S) page URLs are allowed")
        self.chrome.json_request("/json/new?" + quote(url, safe=""), method="PUT")

    def close_empty_pages(self) -> None:
        raw = self.chrome.json_request("/json/list")
        if not isinstance(raw, list):
            raise BrowserUnavailable("invalid Chrome target response")
        for target in raw:
            if not isinstance(target, dict) or target.get("type") != "page":
                continue
            url = target.get("url")
            target_id = target.get("id")
            if url in ("about:blank", "chrome://newtab/") and isinstance(target_id, str):
                self.chrome.text_request("/json/close/" + quote(target_id, safe=""), method="GET")

    @staticmethod
    def _is_page_url(url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def create_browser_server(
    adapter: ChromeBrowserAdapter,
    *,
    address: tuple[str, int] = ("127.0.0.1", 9230),
) -> ThreadingHTTPServer:
    """Create the restricted browser-side API consumed by the slot supervisor."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path == "/browser/readiness":
                    ready = adapter.readiness()
                    self._send_json(
                        200,
                        {"owner": ready.owner, "generation": ready.generation, "cdp_ok": ready.cdp_ok},
                    )
                    return
                if self.path == "/browser/pages":
                    self._send_json(200, {"urls": adapter.list_page_urls()})
                    return
                self.send_error(404)
            except BrowserUnavailable:
                self._send_json(503, {"ok": False, "error_code": "browser_unavailable"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler contract
            try:
                if self.path == "/browser/start":
                    adapter.start()
                elif self.path == "/browser/stop":
                    adapter.stop()
                elif self.path == "/browser/pages/open":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 4096:
                        raise ValueError("invalid body length")
                    adapter.open_page(self.rfile.read(length).decode("utf-8"))
                elif self.path == "/browser/pages/close-empty":
                    adapter.close_empty_pages()
                else:
                    self.send_error(404)
                    return
                self._send_json(200, {"ok": True})
            except (BrowserUnavailable, ValueError, UnicodeDecodeError):
                self._send_json(503, {"ok": False, "error_code": "browser_operation_failed"})

        def _send_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer(address, Handler)
