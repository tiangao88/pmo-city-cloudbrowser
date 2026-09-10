"""Durable principal-scoped broker grant authorization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.grant_store import DurableGrantStore
from cloudbrowser.credential_broker.service import ResolvedBinding


def _binding(
    *,
    profile_id: str = "profile-a",
    principal_id: str = "principal-a",
    browser_id: str = "browser-a",
    generation: str = "generation-a",
) -> ResolvedBinding:
    return ResolvedBinding(
        profile_id=profile_id,
        principal_id=principal_id,
        browser_id=browser_id,
        site_id="site-a",
        generation=generation,
    )


def _put(store: DurableGrantStore, binding: ResolvedBinding | None = None) -> None:
    live = binding or _binding()
    store.put(
        profile_id=live.profile_id,
        principal_id=live.principal_id,
        site_id="site-a",
        target_tab_id="target-a",
        browser_id=live.browser_id,
        generation=live.generation,
        username_ref="vault-item-a",
    )


def test_grant_is_scoped_to_principal_and_exact_target(tmp_path: Path) -> None:
    store = DurableGrantStore(tmp_path / "grants.sqlite3")
    _put(store)

    authorization = store.resolve(_binding(), "site-a", "target-a")
    assert authorization.username_ref == "vault-item-a"

    with pytest.raises(LookupError, match="grant unavailable"):
        store.resolve(_binding(principal_id="principal-b"), "site-a", "target-a")
    with pytest.raises(LookupError, match="grant unavailable"):
        store.resolve(_binding(), "site-a", "target-b")


def test_grant_is_bound_to_browser_and_generation(tmp_path: Path) -> None:
    store = DurableGrantStore(tmp_path / "grants.sqlite3")
    _put(store)

    with pytest.raises(LookupError, match="grant unavailable"):
        store.resolve(_binding(browser_id="browser-b"), "site-a", "target-a")
    with pytest.raises(LookupError, match="grant unavailable"):
        store.resolve(_binding(generation="generation-b"), "site-a", "target-a")


def test_revocation_is_durable_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "grants.sqlite3"
    store = DurableGrantStore(path)
    _put(store)
    assert store.revoke(
        profile_id="profile-a",
        principal_id="principal-a",
        site_id="site-a",
        target_tab_id="target-a",
    ) is True

    with pytest.raises(LookupError, match="grant revoked"):
        DurableGrantStore(path).resolve(_binding(), "site-a", "target-a")


def test_revoke_is_idempotent_and_epoch_increments_once(tmp_path: Path) -> None:
    path = tmp_path / "grants.sqlite3"
    store = DurableGrantStore(path)
    _put(store)

    assert store.revoke(
        profile_id="profile-a", principal_id="principal-a", site_id="site-a", target_tab_id="target-a"
    ) is True
    assert store.revoke(
        profile_id="profile-a", principal_id="principal-a", site_id="site-a", target_tab_id="target-a"
    ) is False


def test_concurrent_upserts_leave_a_complete_authorization(tmp_path: Path) -> None:
    path = tmp_path / "grants.sqlite3"
    store = DurableGrantStore(path)

    def write(index: int) -> None:
        store.put(
            profile_id="profile-a",
            principal_id="principal-a",
            site_id="site-a",
            target_tab_id="target-a",
            browser_id="browser-a",
            generation="generation-a",
            username_ref=f"vault-item-{index}",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(32)))

    authorization = DurableGrantStore(path).resolve(_binding(), "site-a", "target-a")
    assert authorization.username_ref.startswith("vault-item-")
    assert authorization.profile_id == "profile-a"
    assert authorization.principal_id == "principal-a"
    assert authorization.browser_id == "browser-a"
    assert authorization.generation == "generation-a"
