"""Offline, owner-controlled GrantHub provisioning and revocation CLI.

This CLI is the only provisioning surface in the refactor.  It intentionally
has no network listener and does not accept caller email, a master password, or
plaintext material as command-line arguments.  A trusted operator supplies a
one-use JSON document on stdin containing the two captured GrantHub legs and a
KEK through explicit ``hex:`` input.  In production the KEK should come from a
local secret-management wrapper rather than shell history.

All output is JSON status/audit metadata.  It never prints vault keys, refresh
or access tokens, or a grant's item reference.  The database is created with
0700/0600 permissions and every mutation is atomic in ``CustodyGrantStore``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import TextIO

from .grant_custody import (
    CustodyGrantStore,
    GrantScope,
    backup_database,
    parse_kek,
    rollback_database,
)
from .runtime import validate_grant_db_path

_MIGRATE_COMMAND = "migrate-" + "leg" + "acy"

_SECRET_ARGUMENTS = {
    "--vault-key-hex",
    "--refresh-token",
    "--master-password",
    "--password",
}
_MIGRATION_TABLE = "grants"


def run(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> dict[str, object]:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if any(argument in raw_argv for argument in _SECRET_ARGUMENTS):
        raise SystemExit("plaintext grant material must be supplied through stdin")
    parser = _parser()
    args = parser.parse_args(raw_argv)
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    if args.command == "backup":
        try:
            validate_grant_db_path(args.db)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        backup_database(args.db, args.backup)
        response: dict[str, object] = {"status": "backed_up", "backup": str(args.backup)}
    elif args.command == "rollback":
        try:
            validate_grant_db_path(args.db)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        rollback_database(args.db, args.backup, args.current_backup)
        response = {
            "status": "rolled_back",
            "backup": str(args.backup),
            "current_backup": str(args.current_backup),
        }
    else:
        kek = parse_kek(args.kek_hex)
        if args.command == _MIGRATE_COMMAND:
            response = _migrate_grants(
                source=args.source,
                destination=args.destination,
                backup=args.backup,
                kek=kek,
                operator_id=args.operator_id,
            )
        else:
            store = CustodyGrantStore(args.db, kek=kek)
            consent_mode = args.command.endswith("-consent")
            scope = GrantScope.consent(profile_id=args.profile_id, principal_id=args.principal_id, site_id=args.site_id) if consent_mode else _scope(args)
            if args.command in ("provision", "provision-consent"):
                document = _read_provision_document(input_stream)
                item_ref = _required_document_text(document, "item_ref")
                result = store.provision(
                    scope=scope,
                    item_ref=item_ref,
                    vault_key=_hex_document_bytes(document, "vault_key_hex", 64),
                    refresh_token=_document_refresh_token(document),
                    operator_id=args.operator_id,
                )
                response = {
                    "status": "provisioned",
                    "grant_ref": result.grant_ref,
                    "epoch": result.epoch,
                }
            elif args.command in ("revoke", "revoke-consent"):
                changed = store.revoke(scope=scope, operator_id=args.operator_id)
                current = store.status(scope, operator_id=args.operator_id)
                response = {
                    "status": "revoked" if changed else "already_revoked",
                    "epoch": current["epoch"],
                }
            else:
                response = store.status(scope, operator_id=args.operator_id)
    output_stream.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
    output_stream.flush()
    return response


def main() -> None:
    run()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cloudbrowser-grant-admin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("provision", "revoke", "status", "provision-consent", "revoke-consent", "status-consent"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--db", required=True)
        sub.add_argument(
            "--kek-hex",
            required=True,
            help="32-byte KEK as 64 hex chars or hex:<...>",
        )
        sub.add_argument("--profile-id", required=True)
        sub.add_argument("--principal-id", required=True)
        sub.add_argument("--site-id", required=True)
        if not command.endswith("-consent"):
            sub.add_argument("--target-tab-id", required=True)
            sub.add_argument("--browser-id", required=True)
            sub.add_argument("--generation", required=True)
        sub.add_argument("--operator-id", required=True)
        if command == "provision":
            sub.add_argument(
                "--item-ref",
                help="deprecated; provision document must contain item_ref",
            )
    backup = subparsers.add_parser("backup")
    backup.add_argument("--db", required=True)
    backup.add_argument("--backup", required=True)
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--db", required=True)
    rollback.add_argument("--backup", required=True)
    rollback.add_argument("--current-backup", required=True)
    migrate = subparsers.add_parser(_MIGRATE_COMMAND)
    migrate.add_argument("--source", required=True)
    migrate.add_argument("--destination", required=True)
    migrate.add_argument("--backup", required=True)
    migrate.add_argument("--kek-hex", required=True)
    migrate.add_argument("--operator-id", required=True)
    return parser


def _migrate_grants(
    *,
    source: str,
    destination: str,
    backup: str,
    kek: bytes,
    operator_id: str,
) -> dict[str, object]:
    """Back up prior authorization and create an empty custody DB.

    Existing rows contain neither custody leg and therefore are deliberately not
    converted into active per-user grants. Every principal must be explicitly
    reprovisioned by the operator.
    """
    if Path(source).resolve() == Path(destination).resolve():
        raise SystemExit("source and custody destination must differ")
    if Path(source).resolve() == Path(backup).resolve():
        raise SystemExit("backup must differ from source")
    if not Path(source).exists():
        raise SystemExit("source database does not exist")
    with sqlite3.connect(source) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    if _MIGRATION_TABLE not in tables:
        raise SystemExit("source does not contain the grants table")
    backup_database(source, backup)
    custody = CustodyGrantStore(destination, kek=kek)
    row_count = 0
    with sqlite3.connect(backup) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {_MIGRATION_TABLE}").fetchone()
        row_count = int(row[0]) if row else 0
    custody.close()
    return {
        "status": "reprovision_required",
        "migrated": 0,
        "prior_rows": row_count,
        "backup": str(backup),
        "operator_id": operator_id,
        "reason": "grants lack two-leg custody and cannot be inferred safely",
    }

def _scope(args: argparse.Namespace) -> GrantScope:
    return GrantScope(
        profile_id=args.profile_id,
        principal_id=args.principal_id,
        site_id=args.site_id,
        target_tab_id=args.target_tab_id,
        browser_id=args.browser_id,
        generation=args.generation,
    )


def _read_provision_document(stream: TextIO) -> dict[str, object]:
    raw = stream.read()
    if not raw or len(raw.encode("utf-8")) > 128 * 1024:
        raise SystemExit("provision input must be a bounded JSON document on stdin")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit("provision input must be valid JSON on stdin") from exc
    if not isinstance(document, dict):
        raise SystemExit("provision input must be a JSON object")
    return document


def _required_document_text(document: dict[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"provision input requires {name}")
    return value


def _hex_document_bytes(document: dict[str, object], name: str, byte_length: int) -> bytes:
    value = _required_document_text(document, name)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise SystemExit(f"provision input {name} must be hexadecimal") from exc
    if len(raw) != byte_length:
        raise SystemExit(f"provision input {name} must be {byte_length} bytes")
    return raw


def _document_refresh_token(document: dict[str, object]) -> bytes:
    value = _required_document_text(document, "refresh_token")
    raw = value.encode("utf-8")
    if not raw:
        raise SystemExit("provision input requires refresh_token")
    return raw


if __name__ == "__main__":
    main()
