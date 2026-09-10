"""Small stdlib HTTP+JSON client for the trusted browser sidecar."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .transport import BrowserUnavailable

_SELECTOR_QUERY_PREFIX = "selector="
_MAX_PAGE_INFO_QUERY_BYTES = 4096


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

    def request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> object:
        if method not in {"GET", "POST"}:
            raise ValueError("method is not allowed")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("path must be relative to the configured origin")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or ".." in parsed.path or parsed.fragment:
            raise ValueError("path must be a simple relative API path")
        if parsed.query:
            query_is_allowed = (
                method == "GET"
                and parsed.path == "/agent/pages/info"
                and (parsed.query.count("target_tab_id=") == 1 or parsed.query.startswith("selector="))
                and parsed.query.count("selector=") <= 1
                and all(part.split("=", 1)[0] in {"target_tab_id", "selector"} for part in parsed.query.split("&"))
            )
            try:
                query_is_bounded = (
                    len(parsed.query.encode("ascii", "strict")) <= _MAX_PAGE_INFO_QUERY_BYTES
                )
            except UnicodeEncodeError:
                query_is_bounded = False
            if not query_is_allowed or not query_is_bounded:
                raise ValueError("path must be a simple relative API path")
        data = body.encode("utf-8") if body is not None else None
        merged = {"Content-Type": "text/plain; charset=utf-8"} if data is not None else {}
        if headers:
            merged.update(headers)
        request = Request(
            self._base_url + parsed.path + (("?" + parsed.query) if parsed.query else ""),
            data=data,
            method=method,
            headers=merged,
        )
        if timeout_s is not None and timeout_s <= 0:
            raise TimeoutError("browser request deadline expired")
        effective_timeout = min(self._timeout_s, timeout_s) if timeout_s is not None else self._timeout_s
        try:
            with urlopen(request, timeout=effective_timeout) as response:
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
