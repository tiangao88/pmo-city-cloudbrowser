"""Restricted HTTP adapter implementing the supervisor browser transport."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlsplit

from .transport import BrowserReadiness, BrowserUnavailable


class HttpClient(Protocol):
    """Internal request contract; callers never receive raw browser control."""

    def request(self, method: str, path: str, *, body: str | None = None) -> object: ...


class HttpBrowserTransport:
    """Translate narrow lifecycle operations to a trusted browser service."""

    def __init__(self, client: HttpClient, *, expected_owner: str, expected_generation: str) -> None:
        self._client = client
        self._expected_owner = expected_owner
        self._expected_generation = expected_generation

    def start(self) -> None:
        self._expect_ok(self._client.request("POST", "/browser/start"))

    def stop(self) -> None:
        self._expect_ok(self._client.request("POST", "/browser/stop"))

    def readiness(self) -> BrowserReadiness:
        raw = self._client.request("GET", "/browser/readiness")
        if not isinstance(raw, dict):
            raise BrowserUnavailable("invalid browser readiness response")
        owner = raw.get("owner")
        generation = raw.get("generation")
        cdp_ok = raw.get("cdp_ok")
        if (
            not isinstance(owner, str)
            or not isinstance(generation, str)
            or not isinstance(cdp_ok, bool)
            or owner != self._expected_owner
            or generation != self._expected_generation
        ):
            raise BrowserUnavailable("browser readiness binding mismatch")
        return BrowserReadiness(owner, generation, cdp_ok)

    def list_page_urls(self) -> list[str]:
        raw = self._client.request("GET", "/browser/pages")
        if not isinstance(raw, dict) or not isinstance(raw.get("urls"), list):
            raise BrowserUnavailable("invalid browser pages response")
        urls = raw["urls"]
        if not all(isinstance(url, str) for url in urls):
            raise BrowserUnavailable("invalid browser page URL")
        return urls

    def open_page(self, url: str) -> None:
        self._validate_page_url(url)
        self._expect_ok(self._client.request("POST", "/browser/pages/open", body=url))

    def close_empty_pages(self) -> None:
        self._expect_ok(self._client.request("POST", "/browser/pages/close-empty"))

    @staticmethod
    def _validate_page_url(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("only absolute HTTP(S) page URLs are allowed")

    @staticmethod
    def _expect_ok(response: object) -> None:
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise BrowserUnavailable("browser operation was not acknowledged")
