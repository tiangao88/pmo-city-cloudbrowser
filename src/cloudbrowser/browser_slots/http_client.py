"""Small stdlib HTTP+JSON client for the trusted browser sidecar."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .transport import BrowserUnavailable


class HttpJsonClient:
    """Allow only relative browser API paths over a configured HTTP origin."""

    def __init__(self, base_url: str, *, timeout_s: float = 5.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
            raise ValueError("base_url must be an HTTP(S) origin without userinfo")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("base_url must not include a path or query")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_s = timeout_s

    def request(self, method: str, path: str, *, body: str | None = None) -> object:
        if method not in {"GET", "POST"}:
            raise ValueError("method is not allowed")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("path must be relative to the configured origin")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or ".." in parsed.path or parsed.query or parsed.fragment:
            raise ValueError("path must be a simple relative API path")
        data = body.encode("utf-8") if body is not None else None
        request = Request(
            self._base_url + parsed.path,
            data=data,
            method=method,
            headers={"Content-Type": "text/plain; charset=utf-8"} if data is not None else {},
        )
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                if response.status < 200 or response.status >= 300:
                    raise BrowserUnavailable("browser API returned a non-success status")
                raw = response.read(64 * 1024)
                content_type = response.headers.get_content_type()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise BrowserUnavailable("browser API is unavailable") from exc
        if content_type != "application/json":
            raise BrowserUnavailable("browser API returned a non-JSON response")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrowserUnavailable("browser API returned invalid JSON") from exc
