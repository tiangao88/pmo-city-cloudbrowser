"""Compatibility and parser tests for the edge identity boundary.

The static PrincipalMap API is intentionally rejected. These tests keep the
parser's bounded transport behavior while asserting that the production
identity authority is a namespaced PMO link service.
"""

from __future__ import annotations

import pytest

from cloudbrowser.edge_auth import EdgeIdentity, PrincipalMap, PrincipalMapError, parse_edge_identity


def test_valid_edge_attributes_are_parsed_and_canonicalized() -> None:
    identity = parse_edge_identity(
        {
            "Remote-Email": "Owner@Example.COM",
            "Remote-User": "owner",
            "Remote-Name": "Owner Person",
            "Remote-Groups": "PMOC_Users, PMOC_Admins",
        }
    )
    assert identity is not None
    assert identity.email == "owner@example.com"
    assert identity.user == "owner"
    assert identity.name == "Owner Person"
    assert identity.groups == ("PMOC_Users", "PMOC_Admins")
    assert identity.sub is None
    assert identity.principal_subject == "owner"
    assert identity.lookup_candidates == (("user", "owner"),)


def test_sub_is_preferred_over_user_and_email_when_present() -> None:
    identity = parse_edge_identity(
        {
            "Remote-Sub": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
            "Remote-Email": "owner@example.com",
            "Remote-User": "owner",
        }
    )
    assert identity is not None
    assert identity.sub == "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    assert identity.principal_subject == identity.sub
    assert identity.lookup_candidates == (("sub", identity.sub),)


def test_missing_identity_headers_return_none() -> None:
    assert parse_edge_identity({}) is None
    assert parse_edge_identity({"Accept": "text/html"}) is None
    assert parse_edge_identity({"Remote-Name": "Owner"}) is None


def test_user_is_valid_fallback_without_email() -> None:
    identity = parse_edge_identity({"Remote-User": "owner", "Remote-Groups": "PMOC_Users"})
    assert identity is not None
    assert identity.user == "owner"
    assert identity.email is None


def test_email_without_authoritative_key_is_not_an_identity() -> None:
    identity = parse_edge_identity(
        {"Remote-Email": "owner@example.com", "Remote-Groups": "PMOC_Users"}
    )
    assert identity is not None
    assert identity.lookup_candidates == ()
    assert identity.principal_subject is None


def test_email_with_control_characters_is_rejected() -> None:
    for value in ("victim@example.test\r\nX-Evil: 1", "victim@example.test\x00", "a\tb@example.test"):
        assert parse_edge_identity({"Remote-Email": value}) is None, value


def test_overlong_identity_values_are_rejected() -> None:
    assert parse_edge_identity({"Remote-Email": "a" * 300 + "@example.com"}) is None
    assert parse_edge_identity({"Remote-Sub": "x" * 300}) is None


def test_empty_or_whitespace_identity_values_are_rejected() -> None:
    assert parse_edge_identity({"Remote-Email": "  "}) is None
    assert parse_edge_identity({"Remote-Email": ""}) is None
    assert parse_edge_identity({"Remote-User": " "}) is None


def test_invalid_sub_fails_closed_even_with_valid_user() -> None:
    assert parse_edge_identity(
        {"Remote-Sub": "bad sub with spaces", "Remote-User": "owner"}
    ) is None


def test_email_with_unexpected_characters_is_rejected() -> None:
    for value in ("a b@example.com", "a%!b@example.com", "owner@", "@example.com", "owner@exa mple.com"):
        assert parse_edge_identity({"Remote-Email": value}) is None, value


def test_forged_prefix_is_ignored_when_duplicates_are_joined() -> None:
    identity = parse_edge_identity(
        {
            "Remote-Email": "attacker@example.test, victim@example.test",
            "Remote-User": "victim",
        }
    )
    assert identity is not None
    assert identity.email == "victim@example.test"
    assert identity.principal_subject == "victim"


def test_case_insensitive_header_names() -> None:
    identity = parse_edge_identity({"remote-email": "owner@example.com", "REMOTE-USER": "owner"})
    assert identity is not None
    assert identity.principal_subject == "owner"


def test_groups_are_bounded_and_invalid_tokens_dropped() -> None:
    identity = parse_edge_identity(
        {
            "Remote-User": "owner",
            "Remote-Groups": "PMOC_Users, , bad\x00group, PMOC_Admins",
        }
    )
    assert identity is not None
    assert identity.groups == ("PMOC_Users", "PMOC_Admins")


def test_plus_addressing_and_dashes_are_accepted() -> None:
    identity = parse_edge_identity(
        {"Remote-Email": "owner+tag@example-domain.com", "Remote-User": "owner"}
    )
    assert identity is not None
    assert identity.email == "owner+tag@example-domain.com"


def test_edge_identity_repr_never_contains_raw_values() -> None:
    identity = parse_edge_identity({"Remote-Email": "owner@example.com", "Remote-User": "owner"})
    assert identity is not None
    rendered = repr(identity)
    assert "owner@example.com" not in rendered
    assert "owner" not in rendered


def test_static_map_authority_is_rejected() -> None:
    with pytest.raises(PrincipalMapError):
        PrincipalMap(by_subject={"oidc-sub-1": "pmo-user-001"})
    with pytest.raises(PrincipalMapError):
        PrincipalMap.from_file("/tmp/principal-map.json")


def test_documented_shape_helpers() -> None:
    assert EdgeIdentity(email="owner@example.com").principal_subject is None
