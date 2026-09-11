"""Durable consent and one-request browser authority are different scopes."""
from dataclasses import replace
import io
import json
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.grant_custody import CustodyGrantStore, GrantScope, GrantRevoked
from cloudbrowser.credential_broker.service import ResolvedBinding
from cloudbrowser.credential_broker.grant_admin import run

KEK = bytes.fromhex("11" * 32)


def consent():
    return GrantScope.consent(profile_id="profile-alice", principal_id="alice", site_id="site-1")


def provision(store):
    store.provision(scope=consent(), item_ref="test-item", vault_key=bytes.fromhex("22" * 64), refresh_token=b"fake-refresh", operator_id="test-operator")


def binding(generation="g1", browser="slot-1"):
    return ResolvedBinding(profile_id="profile-alice", principal_id="alice", site_id="site-1", browser_id=browser, generation=generation)


def test_consent_survives_restart_generation_and_tab_change(tmp_path):
    c = consent()
    path = tmp_path / "custody.sqlite3"
    store = CustodyGrantStore(path, kek=KEK)
    provision(store)
    first = store.resolve(binding(), "site-1", "tab-1")
    reopened = CustodyGrantStore(path, kek=KEK)
    second = reopened.resolve(binding("g2", "slot-2"), "site-1", "tab-2")
    assert first.username_ref == second.username_ref
    assert (second.browser_id, second.generation, second.target_tab_id) == ("slot-2", "g2", "tab-2")
    with reopened.checkout(second.username_ref) as lease:
        assert lease.scope == c


@pytest.mark.parametrize("field,value", [("principal_id", "bob"), ("profile_id", "profile-bob"), ("site_id", "site-2")])
def test_consent_never_crosses_owner_profile_or_site(tmp_path, field, value):
    consent()
    store = CustodyGrantStore(tmp_path / "custody.sqlite3", kek=KEK)
    provision(store)
    foreign = replace(binding(), **{field: value})
    with pytest.raises(LookupError):
        store.resolve(foreign, foreign.site_id, "tab-new")


def test_revocation_blocks_every_new_binding_and_old_handle(tmp_path):
    c = consent()
    store = CustodyGrantStore(tmp_path / "custody.sqlite3", kek=KEK)
    provision(store)
    first = store.resolve(binding(), "site-1", "tab-1")
    store.revoke(scope=c, operator_id="operator")
    with pytest.raises(LookupError):
        store.resolve(binding("g2"), "site-1", "tab-2")
    with pytest.raises(GrantRevoked):
        with store.checkout(first.username_ref):
            pytest.fail("revoked material exposed")


def test_existing_exact_grant_is_not_silently_widened(tmp_path):
    consent()
    store = CustodyGrantStore(tmp_path / "custody.sqlite3", kek=KEK)
    exact = GrantScope.from_binding(binding(), site_id="site-1", target_tab_id="tab-1")
    store.provision(scope=exact, item_ref="test-item", vault_key=bytes.fromhex("22" * 64), refresh_token=b"fake-refresh", operator_id="operator")
    with pytest.raises(LookupError):
        store.resolve(binding("g2"), "site-1", "tab-2")
    with pytest.raises(ValueError):
        provision(store)


def test_consent_cli_has_no_ephemeral_binding_arguments(tmp_path):
    consent()
    args = ["--db", str(tmp_path / "custody.sqlite3"), "--kek-hex", KEK.hex(), "--profile-id", "profile-alice", "--principal-id", "alice", "--site-id", "site-1", "--operator-id", "operator"]
    doc = json.dumps({"item_ref": "test-item", "vault_key_hex": "22" * 64, "refresh_token": "fake-refresh"})
    result = run(["provision-consent", *args], stdin=io.StringIO(doc), stdout=io.StringIO())
    assert result["status"] == "provisioned"
    assert run(["revoke-consent", *args], stdout=io.StringIO())["status"] == "revoked"


def test_active_consent_cannot_gain_an_unrevoked_exact_alternative(tmp_path):
    store = CustodyGrantStore(tmp_path / "custody.sqlite3", kek=KEK)
    provision(store)
    exact = GrantScope.from_binding(binding(), site_id="site-1", target_tab_id="tab-1")
    with pytest.raises(ValueError):
        store.provision(scope=exact, item_ref="test-item", vault_key=bytes.fromhex("22" * 64), refresh_token=b"fake-refresh", operator_id="operator")


def test_consent_record_cannot_be_used_as_a_request_binding():
    assert not consent().permits_request_scope(consent())
    with pytest.raises(ValueError):
        replace(consent(), target_tab_id="real-tab")
