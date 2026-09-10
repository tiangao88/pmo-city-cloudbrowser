"""Fail-closed grant-state upgrade, migration, backup, and rollback contracts."""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from cloudbrowser.credential_broker.grant_admin import run
from cloudbrowser.credential_broker.grant_custody import CustodyGrantStore, GrantScope
from cloudbrowser.credential_broker.grant_store import DurableGrantStore
from cloudbrowser.credential_broker.runtime import validate_grant_db_path
from cloudbrowser.credential_broker.service import ResolvedBinding

KEK = bytes.fromhex("55" * 32)
VAULT_KEY = bytes.fromhex("66" * 64)


def _scope(principal_id: str = "principal-a") -> GrantScope:
    return GrantScope(
        profile_id="profile-a",
        principal_id=principal_id,
        site_id="site-a",
        target_tab_id="tab-a",
        browser_id="browser-a",
        generation="generation-a",
    )


def _binding(value: GrantScope) -> ResolvedBinding:
    return ResolvedBinding(
        profile_id=value.profile_id,
        principal_id=value.principal_id,
        browser_id=value.browser_id,
        site_id=value.site_id,
        generation=value.generation,
    )


def _write_prior_grant(path: Path, *, principal_id: str = "principal-a") -> None:
    store = DurableGrantStore(path)
    store.put(
        profile_id="profile-a",
        principal_id=principal_id,
        site_id="site-a",
        target_tab_id="tab-a",
        browser_id="browser-a",
        generation="generation-a",
        username_ref="prior-item-ref",
    )


def _provision(store: CustodyGrantStore, value: GrantScope) -> str:
    result = store.provision(
        scope=value,
        item_ref="vault-item-a",
        vault_key=VAULT_KEY,
        refresh_token=b"refresh-a",
        operator_id="operator-a",
    )
    return result.grant_ref


def test_runtime_rejects_unversioned_prior_db_path() -> None:
    with pytest.raises(ValueError, match="prior grant DB path"):
        validate_grant_db_path("/data/state/grants.sqlite3")


def test_runtime_requires_the_versioned_custody_db_filename() -> None:
    with pytest.raises(ValueError, match="grant DB path must"):
        validate_grant_db_path("/data/state/custody.sqlite3")


def test_cli_exposes_migration_and_rollback_commands() -> None:
    from cloudbrowser.credential_broker import grant_admin

    parser = grant_admin._parser()
    subparsers = next(action for action in parser._actions if action.dest == "command")
    assert subparsers.choices is not None
    assert {"migrate-legacy", "backup", "rollback"} <= set(subparsers.choices)


def test_cli_run_uses_process_argv_for_module_execution(monkeypatch) -> None:
    from cloudbrowser.credential_broker import grant_admin

    monkeypatch.setattr(sys, "argv", ["cloudbrowser-grant-admin", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        grant_admin.run()
    assert exc_info.value.code == 0


def test_custody_startup_refuses_prior_grants_table_without_mutating_it(tmp_path: Path) -> None:
    path = tmp_path / "grants.sqlite3"
    _write_prior_grant(path)

    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        before_rows = connection.execute("SELECT COUNT(*) FROM grants").fetchone()[0]

    with pytest.raises(RuntimeError, match="prior grants table"):
        CustodyGrantStore(path, kek=KEK)

    with sqlite3.connect(path) as connection:
        after = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        after_rows = connection.execute("SELECT COUNT(*) FROM grants").fetchone()[0]

    assert after == before
    assert after_rows == before_rows == 1


def test_new_custody_database_is_explicitly_versioned(tmp_path: Path) -> None:
    path = tmp_path / "grant-custody-v1.sqlite3"
    CustodyGrantStore(path, kek=KEK)

    with sqlite3.connect(path) as connection:
        metadata = connection.execute(
            "SELECT schema_version, schema_id FROM grant_metadata"
        ).fetchone()

    assert metadata == (1, "cloudbrowser.grant-custody.v1")


def test_unknown_custody_schema_version_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "grant-custody-v1.sqlite3"
    CustodyGrantStore(path, kek=KEK)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE grant_metadata SET schema_version = 999")
        connection.commit()

    with pytest.raises(RuntimeError, match="unsupported custody schema version"):
        CustodyGrantStore(path, kek=KEK)


def test_unversioned_custody_tables_fail_closed_instead_of_being_upgraded_silently(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unversioned.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE grant_custody (grant_id TEXT PRIMARY KEY, active INTEGER NOT NULL)"
        )
        connection.commit()

    with pytest.raises(RuntimeError, match="missing custody schema metadata"):
        CustodyGrantStore(path, kek=KEK)


def test_offline_legacy_migration_backs_up_and_requires_reprovision_without_copying_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "grants.sqlite3"
    destination = tmp_path / "grant-custody-v1.sqlite3"
    backup = tmp_path / "grants.legacy.backup.sqlite3"
    _write_prior_grant(source)

    result = run(
        [
            "migrate-legacy",
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--backup",
            str(backup),
            "--kek-hex",
            "hex:" + "55" * 32,
            "--operator-id",
            "operator-a",
        ],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )

    assert result["status"] == "reprovision_required"
    assert result["migrated"] == 0
    assert result["backup"] == str(backup)
    assert destination.exists()

    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 1
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT COUNT(*) FROM grant_custody").fetchone()[0] == 0

    custody = CustodyGrantStore(destination, kek=KEK)
    with pytest.raises(LookupError, match="grant unavailable"):
        custody.resolve(_binding(_scope()), "site-a", "tab-a")
    with pytest.raises(LookupError, match="grant unavailable"):
        custody.resolve(_binding(_scope("principal-b")), "site-a", "tab-a")


def test_backup_and_rollback_restore_all_custody_users_without_cross_user_copy(
    tmp_path: Path,
) -> None:
    path = tmp_path / "grant-custody-v1.sqlite3"
    backup = tmp_path / "custody.before.sqlite3"
    current_backup = tmp_path / "custody.current.sqlite3"
    store = CustodyGrantStore(path, kek=KEK)
    first_ref = _provision(store, _scope("principal-a"))
    second_ref = _provision(store, _scope("principal-b"))

    backed_up = run(
        ["backup", "--db", str(path), "--backup", str(backup)],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )
    assert backed_up == {"status": "backed_up", "backup": str(backup)}

    assert store.revoke(scope=_scope("principal-a"), operator_id="operator-a") is True
    assert store.resolve(_binding(_scope("principal-b")), "site-a", "tab-a").username_ref.startswith(
        "grantref:v1."
    )

    rolled_back = run(
        [
            "rollback",
            "--db",
            str(path),
            "--backup",
            str(backup),
            "--current-backup",
            str(current_backup),
        ],
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )
    assert rolled_back == {
        "status": "rolled_back",
        "backup": str(backup),
        "current_backup": str(current_backup),
    }

    restored = CustodyGrantStore(path, kek=KEK)
    assert restored.resolve(_binding(_scope("principal-a")), "site-a", "tab-a").username_ref == first_ref
    assert restored.resolve(_binding(_scope("principal-b")), "site-a", "tab-a").username_ref == second_ref

    with sqlite3.connect(current_backup) as connection:
        assert connection.execute("SELECT COUNT(*) FROM grant_custody").fetchone()[0] == 2


def test_migration_cli_rejects_plaintext_material_arguments(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="stdin"):
        run(
            [
                "migrate-legacy",
                "--source",
                str(tmp_path / "legacy.sqlite3"),
                "--destination",
                str(tmp_path / "custody.sqlite3"),
                "--backup",
                str(tmp_path / "backup.sqlite3"),
                "--kek-hex",
                "hex:" + "55" * 32,
                "--operator-id",
                "operator-a",
                "--refresh-token",
                "secret",
            ],
            stdin=io.StringIO(),
            stdout=io.StringIO(),
        )
