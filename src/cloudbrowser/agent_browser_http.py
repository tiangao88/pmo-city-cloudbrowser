"""HTTP client for the narrow agent browser sidecar API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

if TYPE_CHECKING:
    from cloudbrowser.credential_broker.deadline import BrokerDeadline
    from cloudbrowser.credential_broker.runtime import LiveBrowserBinding

from .browser_slots import BrowserReadiness, BrowserUnavailable
from .browser_slots.http_transport import HttpClient
from .credential_broker.deadline import BrokerDeadline, invoke_transport


class AgentBrowserClient(HttpClient, Protocol):
    """Internal browser-sidecar request contract."""


@dataclass
class HttpAgentBrowser:
    """Adapt the browser sidecar transport to restricted agent callbacks."""

    transport: "HttpAgentBrowserTransport"

    def readiness(self, *, deadline: BrokerDeadline | None = None) -> BrowserReadiness:
        return self.transport.readiness(deadline=deadline)

    def live_binding(self, *, deadline: BrokerDeadline | None = None) -> "LiveBrowserBinding":
        return self.transport.live_binding(deadline=deadline)

    def list_pages(self, *, deadline: BrokerDeadline | None = None) -> list[dict[str, str]]:
        return self.transport.list_pages(deadline=deadline)

    def navigate(
        self,
        target_tab_id: str,
        url: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        self.transport.navigate(target_tab_id, url, deadline=deadline)

    def click(
        self,
        target_tab_id: str,
        selector: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        self.transport.click(target_tab_id, selector, deadline=deadline)

    def type_text(
        self,
        target_tab_id: str,
        selector: str,
        text: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        self.transport.type_text(target_tab_id, selector, text, deadline=deadline)

    def page_info(
        self,
        target_tab_id: str,
        selector: str | None = None,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> dict[str, str]:
        return self.transport.page_info(target_tab_id, selector, deadline=deadline)


@dataclass
class HttpAgentBrowserTransport:
    """Use only explicitly allowlisted page operations."""

    client: AgentBrowserClient
    expected_owner: str
    expected_generation: str
    request_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        if self.request_timeout_s <= 0 or self.request_timeout_s > 125:
            raise ValueError("agent browser request timeout is invalid")
        client_timeout = getattr(self.client, "_timeout_s", None)
        if isinstance(client_timeout, (int, float)) and client_timeout < self.request_timeout_s:
            try:
                setattr(self.client, "_timeout_s", float(self.request_timeout_s))
            except (AttributeError, TypeError) as exc:
                raise ValueError("agent browser client timeout is too short") from exc

    def rotate_binding(self, principal_id: str, generation: str) -> None:
        """Adopt a server-minted owner/generation for later readiness checks."""

        if not isinstance(principal_id, str) or not principal_id or len(principal_id) > 256:
            raise ValueError("principal_id is invalid")
        if not isinstance(generation, str) or not generation or len(generation) > 256:
            raise ValueError("generation is invalid")
        self.expected_owner = principal_id
        self.expected_generation = generation

    def live_binding(self, *, deadline: BrokerDeadline | None = None) -> "LiveBrowserBinding":
        from cloudbrowser.credential_broker.runtime import LiveBrowserBinding

        readiness = self._readiness_payload(deadline=deadline)
        if not readiness["cdp_ok"]:
            raise BrowserUnavailable("agent browser is not ready")
        return LiveBrowserBinding(
            profile_id=str(readiness.get("profile_id", "profile-unassigned")),
            principal_id=str(readiness["owner"]),
            browser_id=str(readiness.get("browser_id", "browser-unassigned")),
            generation=str(readiness["generation"]),
        )

    def _readiness_payload(
        self,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> dict[str, str | bool]:
        raw = invoke_transport(
            self.client.request,
            "GET",
            "/agent/readiness",
            deadline=deadline,
        )
        if not isinstance(raw, dict):
            raise BrowserUnavailable("invalid agent browser readiness")
        owner, generation, cdp_ok = raw.get("owner"), raw.get("generation"), raw.get("cdp_ok")
        profile_id = raw.get("profile_id", "profile-unassigned")
        browser_id = raw.get("browser_id", "browser-unassigned")
        if (
            not isinstance(owner, str)
            or not isinstance(generation, str)
            or not isinstance(profile_id, str)
            or not isinstance(browser_id, str)
            or not isinstance(cdp_ok, bool)
        ):
            raise BrowserUnavailable("invalid agent browser readiness")
        return {
            "profile_id": str(profile_id),
            "owner": str(owner),
            "browser_id": str(browser_id),
            "generation": str(generation),
            "cdp_ok": bool(cdp_ok),
        }

    def readiness(self, *, deadline: BrokerDeadline | None = None) -> BrowserReadiness:
        readiness = self._readiness_payload(deadline=deadline)
        owner = str(readiness["owner"])
        generation = str(readiness["generation"])
        cdp_ok = bool(readiness["cdp_ok"])
        if owner != self.expected_owner or generation != self.expected_generation:
            raise BrowserUnavailable("agent browser readiness binding mismatch")
        return BrowserReadiness(owner, generation, cdp_ok)

    def list_pages(self, *, deadline: BrokerDeadline | None = None) -> list[dict[str, str]]:
        raw = invoke_transport(
            self.client.request,
            "GET",
            "/agent/pages",
            deadline=deadline,
        )
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("pages"), list)
            or len(raw["pages"]) > 32
        ):
            raise BrowserUnavailable("invalid agent browser pages response")
        pages: list[dict[str, str]] = []
        for page in raw["pages"]:
            if not isinstance(page, dict) or not all(
                isinstance(page.get(key), str) and page[key]
                for key in ("tab_id", "url", "title")
            ):
                raise BrowserUnavailable("invalid agent browser page")
            if any(
                len(page[key].encode("utf-8")) > limit
                for key, limit in (
                    ("tab_id", 256),
                    ("url", 2048),
                    ("title", 4096),
                )
            ):
                raise BrowserUnavailable("agent browser page is too large")
            pages.append({key: page[key] for key in ("tab_id", "url", "title")})
        return pages

    def navigate(
        self,
        target_tab_id: str,
        url: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        body = self._action_json({"target_tab_id": target_tab_id, "value": url})
        self._expect_ok(
            invoke_transport(
                self.client.request,
                "POST",
                "/agent/pages/navigate",
                body=body,
                deadline=deadline,
            )
        )

    def click(
        self,
        target_tab_id: str,
        selector: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        body = self._action_json({"target_tab_id": target_tab_id, "value": selector})
        self._expect_ok(
            invoke_transport(
                self.client.request,
                "POST",
                "/agent/pages/click",
                body=body,
                deadline=deadline,
            )
        )

    def type_text(
        self,
        target_tab_id: str,
        selector: str,
        text: str,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> None:
        body = self._action_json(
            {"target_tab_id": target_tab_id, "selector": selector, "text": text}
        )
        self._expect_ok(
            invoke_transport(
                self.client.request,
                "POST",
                "/agent/pages/type",
                body=body,
                deadline=deadline,
            )
        )

    def page_info(
        self,
        target_tab_id: str,
        selector: str | None = None,
        *,
        deadline: BrokerDeadline | None = None,
    ) -> dict[str, str]:
        query = "target_tab_id=" + quote(target_tab_id, safe="")
        if selector is not None:
            query += "&selector=" + quote(selector, safe="")
        raw = invoke_transport(
            self.client.request,
            "GET",
            "/agent/pages/info?" + query,
            deadline=deadline,
        )
        if not isinstance(raw, dict) or not all(
            isinstance(raw.get(key), str) for key in ("url", "title", "text")
        ):
            raise BrowserUnavailable("invalid agent page state")
        for key, limit in (("url", 2048), ("title", 4096), ("text", 4096)):
            if len(raw[key].encode("utf-8")) > limit:
                raise BrowserUnavailable("agent page state is too large")
        return {key: raw[key] for key in ("url", "title", "text")}

    @staticmethod
    def _action_json(payload: dict[str, str]) -> str:
        import json

        return json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def _expect_ok(response: object) -> None:
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise BrowserUnavailable("agent browser operation was not acknowledged")
