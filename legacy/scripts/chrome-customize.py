#!/usr/bin/env python3
"""Apply and verify PMO City security customizations for embedded Chrome.

This is deliberately version-independent. It is run at container boot to
install managed policy and before every Chrome launch to re-apply profile
preferences, purge any legacy saved-password database, validate the unpacked
extension, and record the exact browser/extension versions that were prepared.
Any missing mandatory input fails closed before Chrome starts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable

POLICY_NAME = "pmo-city-security.json"
REQUIRED_POLICY = {
    # Vaultwarden/GrantHub is the only credential store. Chrome may neither
    # offer to save nor retain newly-entered passwords.
    "PasswordManagerEnabled": False,
    # Embedded Chrome is a task surface, not a second personal data vault.
    "AutofillAddressEnabled": False,
    "AutofillCreditCardEnabled": False,
    # Avoid a second credential-warning surface competing with Vaultwarden.
    "PasswordLeakDetectionEnabled": False,
    # Existing PMO City decisions: downloads only; no PDF renderer or popup.
    "PDFViewerEnabled": False,
    "TranslateEnabled": False,
}


def _atomic_json(path: Path, data: dict, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def install_policies(dirs: Iterable[Path | str]) -> None:
    """Install the same mandatory policy for stock Chrome and official CfT."""
    for raw in dirs:
        directory = Path(raw)
        _atomic_json(directory / POLICY_NAME, REQUIRED_POLICY)
        print(f"chrome-customize: installed mandatory policy in {directory}")


def _read_json(path: Path, *, required: bool = False) -> dict:
    if not path.exists():
        if required:
            raise RuntimeError(f"required file missing: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"invalid JSON at {path}: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object at {path}")
    return data


def _policy_digest(policy: dict) -> str:
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_policy(policy_file: Path) -> dict:
    policy = _read_json(policy_file, required=True)
    wrong = {k: (policy.get(k), expected) for k, expected in REQUIRED_POLICY.items()
             if policy.get(k) != expected}
    if wrong:
        raise RuntimeError(f"mandatory Chrome policy mismatch: {wrong}")
    return policy


def purge_saved_passwords(profile: Path) -> int:
    """Remove Chrome's local login databases while Chrome is stopped."""
    removed = 0
    for path in profile.rglob("Login Data*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)
            removed += 1
        elif path.is_dir():
            shutil.rmtree(path)
            removed += 1
    return removed


def prepare_profile(profile: Path | str, policy_file: Path | str,
                    extension_dir: Path | str, *, browser_version: str,
                    restore_mode: str = "fresh-session") -> None:
    profile = Path(profile)
    policy_file = Path(policy_file)
    extension_dir = Path(extension_dir)
    profile.mkdir(parents=True, exist_ok=True)

    policy = validate_policy(policy_file)
    manifest = _read_json(extension_dir / "manifest.json", required=True)
    extension_version = str(manifest.get("version") or "")
    if not extension_version:
        raise RuntimeError("tabbar extension manifest has no version")

    prefs_path = profile / "Preferences"
    prefs = _read_json(prefs_path)
    prefs["credentials_enable_service"] = False
    prefs["credentials_enable_autosignin"] = False
    prefs.setdefault("profile", {})["password_manager_enabled"] = False
    prefs.setdefault("autofill", {})["profile_enabled"] = False
    prefs.setdefault("autofill", {})["credit_card_enabled"] = False
    if restore_mode not in {"fresh-session", "last-session"}:
        raise RuntimeError(f"unsupported restore mode: {restore_mode}")
    prefs.setdefault("session", {})["restore_on_startup"] = (
        1 if restore_mode == "last-session" else 5
    )
    prefs.setdefault("translate", {})["enabled"] = False
    _atomic_json(prefs_path, prefs, mode=0o600)

    removed = purge_saved_passwords(profile)
    receipt = {
        "schema": 1,
        "browser_version": browser_version.strip(),
        "extension_version": extension_version,
        "policy_sha256": _policy_digest(policy),
        "password_storage": "disabled-and-purged",
        "customizations": [
            "managed-security-policy",
            "password-manager-disabled",
            "autofill-disabled",
            "saved-password-db-purged",
            f"{restore_mode}-startup",
            "translate-disabled",
            "tabbar-extension-validated",
        ],
    }
    _atomic_json(profile / ".pmo-city-customization.json", receipt, mode=0o600)
    print("chrome-customize: profile ready; "
          f"browser={receipt['browser_version']!r} extension={extension_version} "
          f"saved-password-files-removed={removed}")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_install = sub.add_parser("install-policy")
    p_install.add_argument("directories", nargs="+")
    p_profile = sub.add_parser("prepare-profile")
    p_profile.add_argument("--profile", required=True)
    p_profile.add_argument("--policy", required=True)
    p_profile.add_argument("--extension", required=True)
    p_profile.add_argument("--browser-version", required=True)
    p_profile.add_argument("--restore-mode", choices=("fresh-session", "last-session"),
                           default="fresh-session")
    args = parser.parse_args()
    try:
        if args.command == "install-policy":
            install_policies(args.directories)
        else:
            prepare_profile(args.profile, args.policy, args.extension,
                            browser_version=args.browser_version,
                            restore_mode=args.restore_mode)
    except Exception as e:
        print(f"chrome-customize: FATAL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
