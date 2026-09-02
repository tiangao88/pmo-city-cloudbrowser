"""HTTP client for the narrow agent browser sidecar API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from .browser_slots import BrowserReadiness, BrowserUnavailable
from .browser_slots.http_transport import HttpClient


class AgentBrowserClient(HttpClient, Protocol):
    """Internal browser-sidecar request contract."""


@dataclass
class HttpAgentBrowser:
    """Adapt the browser sidecar transport to restricted agent callbacks."""

    transport: "HttpAgentBrowserTransport"

    def readiness(self) -> BrowserReadiness:
        return self.transport.readiness()

    def list_pages(self) -> list[dict[str, str]]:
        return self.transport.list_pages()

    def navigate(self, url: str) -> None:
        self.transport.navigate(url)

    def click(self, selector: str) -> None:
        self.transport.click(selector)

    def type_text(self, selector: str, text: str) -> None:
        self.transport.type_text(selector, text)

    def page_info(self, selector: str | None = None) -> dict[str, str]:
        return self.transport.page_info(selector)


@dataclass
class HttpAgentBrowserTransport:
    """Use only explicitly allowlisted page operations."""

    client: AgentBrowserClient
    expected_owner: str
    expected_generation: str

    def readiness(self) -> BrowserReadiness:
        raw = self.client.request("GET", "/agent/readiness")
        if not isinstance(raw, dict):
            raise BrowserUnavailable("invalid agent browser readiness")
        owner, generation, cdp_ok = raw.get("owner"), raw.get("generation"), raw.get("cdp_ok")
        if not isinstance(owner, str) or not isinstance(generation, str) or not isinstance(cdp_ok, bool):
            raise BrowserUnavailable("invalid agent browser readiness")
        if owner != self.expected_owner or generation != self.expected_generation:
            raise BrowserUnavailable("agent browser readiness binding mismatch")
        return BrowserReadiness(owner, generation, cdp_ok)

    def list_pages(self) -> list[dict[str, str]]:
        raw = self.client.request("GET", "/agent/pages")
        if not isinstance(raw, dict) or not isinstance(raw.get("pages"), list) or len(raw["pages"]) > 32:
            raise BrowserUnavailable("invalid agent browser pages response")
        pages: list[dict[str, str]] = []
        for page in raw["pages"]:
            if not isinstance(page, dict) or not all(
                isinstance(page.get(key), str) and page[key]
                for key in ("tab_id", "url", "title")
            ):
                raise BrowserUnavailable("invalid agent browser page")
            pages.append({key: page[key] for key in ("tab_id", "url", "title")})
        return pages

    def navigate(self, url: str) -> None:
        self._expect_ok(self.client.request("POST", "/agent/pages/navigate", body=url))

    def click(self, selector: str) -> None:
        self._expect_ok(self.client.request("POST", "/agent/pages/click", body=selector))

    def type_text(self, selector: str, text: str) -> None:
        self._expect_ok(self.client.request("POST", "/agent/pages/type", body=selector + "\n" + text))

    def page_info(self, selector: str | None = None) -> dict[str, str]:
        path = "/agent/pages/info"
        if selector:
            path += "?selector=" + quote(selector, safe="")
        raw = self.client.request("GET", path)
        if not isinstance(raw, dict) or not all(
            isinstance(raw.get(key), str) for key in ("url", "title", "text")
        ):
            raise BrowserUnavailable("invalid agent page state")
        return {key: raw[key] for key in ("url", "title", "text")}

    @staticmethod
    def _expect_ok(response: object) -> None:
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise BrowserUnavailable("agent browser operation was not acknowledged")
