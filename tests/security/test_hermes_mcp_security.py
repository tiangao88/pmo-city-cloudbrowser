"""Security regression tests for Hermes-to-CloudBrowser MCP mediation."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from cloudbrowser.hermes_mcp import CloudBrowserHttpClient, HermesMcpServer, _NoRedirects


ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://cloudbrowser.example.test",
        "https://user:pass@cloudbrowser.example.test",
        "https://cloudbrowser.example.test/path",
        "https://cloudbrowser.example.test/?query=secret",
        "file:///tmp/socket",
    ],
)
def test_remote_edge_origin_must_be_https_and_cannot_carry_credentials(base_url: str) -> None:
    with pytest.raises(ValueError):
        CloudBrowserHttpClient(base_url=base_url, authorization="Bearer control-token")


@pytest.mark.parametrize(
    ("authorization", "cookie"),
    [("", ""), ("Bearer one", "session=two"), ("Bearer secret\r\nRemote-Sub: victim", "")],
)
def test_exactly_one_bounded_authentication_channel_is_required(
    authorization: str, cookie: str
) -> None:
    with pytest.raises(ValueError):
        CloudBrowserHttpClient(
            base_url="https://cloudbrowser.example.test",
            authorization=authorization,
            cookie=cookie,
        )


def test_redirect_is_not_followed_and_authentication_is_not_sent_to_redirect_target() -> None:
    calls = []

    class RedirectingOpener:
        def open(self, request, timeout: float):  # noqa: ANN001
            calls.append(request)
            raise HTTPError(
                request.full_url,
                307,
                "redirect",
                {"Location": "https://attacker.example/steal"},
                None,
            )

    client = CloudBrowserHttpClient(
        base_url="https://cloudbrowser.example.test",
        authorization="Bearer do-not-leak",
        opener=RedirectingOpener(),
    )
    result = client.agent("tabs_list", {})
    assert result == {"status": "failed", "error_code": "unauthorized"}
    assert len(calls) == 1
    assert calls[0].full_url == "https://cloudbrowser.example.test/ui/agent/tabs_list"
    assert _NoRedirects().redirect_request(None, None, 307, "", {}, "https://attacker.example") is None


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("raw_cdp", {}),
        ("cloudbrowser_page_info", {"target_tab_id": "tab", "cookies": True}),
        ("cloudbrowser_type", {"target_tab_id": "tab", "selector": "#p", "text": "x", "password": "secret"}),
        ("cloudbrowser_credential_login", {"site_id": "site", "target_tab_id": "tab", "username_ref": "victim"}),
    ],
)
def test_unknown_or_expanded_tool_inputs_fail_before_http(name: str, arguments: dict) -> None:
    class NeverClient:
        def __getattr__(self, attr: str):
            raise AssertionError("invalid MCP request reached CloudBrowser HTTP")

    response = HermesMcpServer(client=NeverClient()).handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    assert response is not None
    assert response["result"]["isError"] is True
    assert "secret" not in json.dumps(response)


def test_transport_failure_never_echoes_auth_material() -> None:
    client = CloudBrowserHttpClient(
        base_url="http://127.0.0.1:1",
        authorization="Bearer never-echo-this",
        timeout_s=0.05,
    )
    result = client.agent("tabs_list", {})
    assert result == {"status": "failed", "error_code": "service_unavailable"}
    assert "never-echo-this" not in repr(client)
    assert "never-echo-this" not in json.dumps(result)


def test_supported_hermes_integration_contains_no_raw_cdp_driver() -> None:
    integration = ROOT / "integrations" / "hermes"
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in integration.rglob("*")
        if path.is_file()
    )
    assert "BU_CDP_URL" not in text
    assert "browser_harness.helpers" not in text
    assert "Runtime.evaluate" not in text
    assert not (integration / "pmoc-cdp-cloudbrowser" / "scripts" / "pmoc_cb.py").exists()
    assert (integration / "cloudbrowser" / "SKILL.md").is_file()
