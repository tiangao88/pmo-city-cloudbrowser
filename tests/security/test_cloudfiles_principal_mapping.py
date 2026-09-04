"""Compatibility tests confirming static identity maps are retired."""

from __future__ import annotations

import pytest

from cloudbrowser.cloudfiles_entrypoint import _edge_auth_mode
from cloudbrowser.edge_auth import PrincipalMap, PrincipalMapError, build_principal_map


def test_static_map_authority_is_rejected() -> None:
    with pytest.raises(PrincipalMapError):
        PrincipalMap(by_subject={"oidc-sub-1": "pmo-user-001"})
    with pytest.raises(PrincipalMapError):
        PrincipalMap.from_file("/tmp/principal-map.json")


def test_build_principal_map_is_removed(monkeypatch) -> None:
    monkeypatch.delenv("CB_PRINCIPAL_MAP_PATH", raising=False)
    with pytest.raises(PrincipalMapError):
        build_principal_map()


def test_edge_middleware_requires_identity_link_client() -> None:
    from cloudbrowser.cloudfiles import identity_adapter

    with pytest.raises(TypeError):
        identity_adapter.edge_session_middleware(lambda environ, start: [])  # type: ignore[call-arg]


def test_empty_edge_mode_remains_unset(monkeypatch) -> None:
    monkeypatch.setenv("CB_EDGE_AUTH", "")
    assert _edge_auth_mode() is None
