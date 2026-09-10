"""Red tests for the offline operator GrantHub CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.grant_admin import run

KEK = "hex:" + "33" * 32
VAULT_KEY = "44" * 64
REFRESH = "operator-refresh-token"


def _scope_args(db: Path, *, include_item: bool = False, include_kek: bool = False) -> list[str]:
    args = [
        "--db",
        str(db),
        "--profile-id",
        "profile-1",
        "--principal-id",
        "principal-1",
        "--site-id",
        "site-1",
        "--target-tab-id",
        "tab-1",
        "--browser-id",
        "browser-1",
        "--generation",
        "generation-1",
        "--operator-id",
        "operator-1",
    ]
    if include_item:
        args[args.index("--generation") + 2 : args.index("--generation") + 2] = [
            "--item-ref",
            "vault-item-1",
        ]
    if include_kek:
        args.extend(["--kek-hex", KEK])
    return args


def test_provision_reads_material_from_stdin_and_returns_only_opaque_status(tmp_path: Path) -> None:
    db = tmp_path / "grants.sqlite3"
    material_doc = {
        "vault_key_hex": VAULT_KEY,
        "refresh_token": REFRESH,
        "item_ref": "vault-item-1",
    }
    material = io.StringIO(json.dumps(material_doc) + "\n")

    result = run(
        ["provision", *_scope_args(db, include_item=True), "--kek-hex", KEK],
        stdin=material,
        stdout=io.StringIO(),
    )

    assert result["status"] == "provisioned"
    assert result["epoch"] == 1
    assert result["grant_ref"].startswith("grantref:v1.")
    encoded = json.dumps(result)
    assert VAULT_KEY not in encoded
    assert REFRESH not in encoded
    assert "principal-1" not in result["grant_ref"]


def test_revoke_is_operator_audited_and_status_is_non_secret(tmp_path: Path) -> None:
    db = tmp_path / "grants.sqlite3"
    provision_doc = {
        "vault_key_hex": VAULT_KEY,
        "refresh_token": REFRESH,
        "item_ref": "vault-item-1",
    }
    provision_input = io.StringIO(json.dumps(provision_doc) + "\n")
    provision_result = run(
        ["provision", *_scope_args(db, include_item=True), "--kek-hex", KEK],
        stdin=provision_input,
        stdout=io.StringIO(),
    )

    revoked = run(
        ["revoke", *_scope_args(db, include_kek=True)],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )
    assert revoked == {"status": "revoked", "epoch": 2}

    status = run(
        ["status", *_scope_args(db, include_kek=True)],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )
    assert status["active"] is False
    assert status["usable"] is False
    assert provision_result["grant_ref"] != ""


def test_cli_rejects_plaintext_secret_arguments(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="stdin"):
        run(
            [
                "provision",
                *_scope_args(tmp_path / "grants.sqlite3", include_item=True),
                "--kek-hex",
                KEK,
                "--vault-key-hex",
                VAULT_KEY,
            ],
            stdin=io.StringIO(),
            stdout=io.StringIO(),
        )


def test_cli_does_not_use_legacy_email_or_password(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CB_VAULT_EMAIL", "legacy@example.invalid")
    monkeypatch.setenv("CB_VAULT_PASSWORD", "legacy-password")
    db = tmp_path / "grants.sqlite3"
    result = run(
        ["status", *_scope_args(db, include_kek=True)],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )
    assert result["active"] is False
    assert "legacy-password" not in json.dumps(result)
