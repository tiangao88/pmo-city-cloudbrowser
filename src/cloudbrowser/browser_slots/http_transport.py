"""Restricted HTTP adapter implementing the supervisor browser transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from cloudbrowser.credential_broker.deadline import BrokerDeadline, invoke_transport

if TYPE_CHECKING:
    from .lifecycle import BrowserBinding

from .transport import BrowserReadiness, BrowserUnavailable


class HttpClient(Protocol):
    """Internal request contract; callers never receive raw browser control."""

    def request(
        self,
        method: str,
        path: str,
        *,
        body: str | None = None,
        headers: "dict[str, str] | None" = None,
        timeout_s: float | None = None,
    ) -> object: ...


class HttpBrowserTransport:
    """Translate narrow lifecycle operations to a trusted browser service."""

    def __init__(
        self,
        client: HttpClient,
        *,
        expected_owner: str,
        expected_generation: str,
    ) -> None:
        self._client = client
        self._expected_owner = expected_owner
        self._expected_generation = expected_generation

    def client(self) -> HttpClient:
        """Return the configured narrow HTTP client for adapter composition."""
        return self._client

    @property
    def expected_owner(self) -> str:
        return self._expected_owner

    @property
    def expected_generation(self) -> str:
        return self._expected_generation

    def rotate_binding(self, principal_id: str, generation: str) -> None:
        """Adopt a server-minted owner/generation for later readiness checks.

        Used by the agent-control lease rotation: after the browser itself
        was rebound, subsequent readiness probes must expect the new binding
        instead of the statically configured boot identity.
        """

        if not isinstance(principal_id, str) or not principal_id or len(principal_id) > 256:
            raise ValueError("principal_id is invalid")
        if not isinstance(generation, str) or not generation or len(generation) > 256:
            raise ValueError("generation is invalid")
        self._expected_owner = principal_id
        self._expected_generation = generation

    def start(self, *, deadline: BrokerDeadline | None = None) -> None:
        self._expect_ok(
            invoke_transport(
                self._client.request,
                "POST",
                "/browser/start",
                deadline=deadline,
            )
        )

    def stop(self, *, deadline: BrokerDeadline | None = None) -> None:
        self._expect_ok(
            invoke_transport(
                self._client.request,
                "POST",
                "/browser/stop",
                deadline=deadline,
            )
        )

    def readiness(self, *, deadline: BrokerDeadline | None = None) -> BrowserReadiness:
        raw = invoke_transport(
            self._client.request,
            "GET",
            "/browser/readiness",
            deadline=deadline,
        )
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

    def list_page_urls(self, *, deadline: BrokerDeadline | None = None) -> list[str]:
        raw = invoke_transport(
            self._client.request,
            "GET",
            "/browser/pages",
            deadline=deadline,
        )
        if not isinstance(raw, dict) or not isinstance(raw.get("urls"), list):
            raise BrowserUnavailable("invalid browser pages response")
        urls = raw["urls"]
        if not all(isinstance(url, str) for url in urls):
            raise BrowserUnavailable("invalid browser page URL")
        return urls

    def open_page(self, url: str, *, deadline: BrokerDeadline | None = None) -> None:
        self._validate_page_url(url)
        self._expect_ok(
            invoke_transport(
                self._client.request,
                "POST",
                "/browser/pages/open",
                body=url,
                deadline=deadline,
            )
        )

    def close_empty_pages(self, *, deadline: BrokerDeadline | None = None) -> None:
        self._expect_ok(
            invoke_transport(
                self._client.request,
                "POST",
                "/browser/pages/close-empty",
                deadline=deadline,
            )
        )

    def push_binding(self, binding: "BrowserBinding") -> None:
        """Push a server-minted binding to the browser service (secret-gated)."""

        import json as _json

        payload = _json.dumps(
            {
                "principal_id": binding.principal_id,
                "profile_id": binding.profile_id,
                "browser_id": binding.browser_id,
                "generation": binding.generation,
            }
        )
        import os as _os

        secret = _os.environ.get("CB_ROUTER_SHARED_SECRET", "")
        self._expect_ok(
            self._client.request(
                "POST",
                "/browser/binding",
                body=payload,
                headers={"X-CB-Trusted-Secret": secret},
            )
        )
        # The browser acknowledged the rebind, so every later readiness probe
        # reports the new identity; keep the transport's expectations in step
        # or adopt-then-wake would fail closed against the previous owner.
        self._expected_owner = binding.principal_id
        self._expected_generation = binding.generation

    @staticmethod
    def _validate_page_url(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("only absolute HTTP(S) page URLs are allowed")

    @staticmethod
    def _expect_ok(response: object) -> None:
        if not isinstance(response, dict) or response.get("ok") is not True:
            raise BrowserUnavailable("browser operation was not acknowledged")
