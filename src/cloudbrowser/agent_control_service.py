"""Agent-control service builder with explicit narrow capability injection."""

from __future__ import annotations

from .agent_browser_http import HttpAgentBrowser, HttpAgentBrowserTransport
from .agent_control import AgentControlService, RestrictedAgentBrowser
from .browser_slots.http_transport import HttpBrowserTransport


def build_agent_control_server(
    transport: HttpBrowserTransport,
    *,
    principal_id: str,
    browser_id: str,
    generation: str,
    page_api: RestrictedAgentBrowser | None = None,
    address: tuple[str, int] = ("127.0.0.1", 8090),
    shared_secret: str | None = None,
):
    """Build agent control from the server-owned transport."""
    if page_api is not None:
        raise ValueError("page_api override is not permitted")
    browser = HttpAgentBrowser(
        HttpAgentBrowserTransport(
            transport.client(),
            expected_owner=principal_id,
            expected_generation=generation,
        )
    )
    return AgentControlService.create_server(
        browser,
        principal_id=principal_id,
        browser_id=browser_id,
        generation=generation,
        shared_secret=shared_secret,
        address=address,
    )


__all__ = ["build_agent_control_server"]
