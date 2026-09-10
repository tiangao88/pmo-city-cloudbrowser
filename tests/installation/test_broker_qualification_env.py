"""Step-17 credential-broker qualification runtime environment contract.

The broker image qualification step must start the container with the
server-owned grant custody configuration the broker runtime requires, and
must not carry obsolete credential-broker environment (the old
shared-secret / Vault-login model was removed).

The broker startup fail-closed contract is enforced by
``cloudbrowser.credential_broker.runtime.build_broker_api``; this test pins
the CI workflow to that same contract so the qualification step cannot
silently regress into "health-only" boot or crash on a missing required
variable.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "build-images.yml"

QUALIFICATION_STEP = "Qualify published image"

# Broker runtime hard requirements (see
# src/cloudbrowser/credential_broker/runtime.py build_broker_api).
BROKER_REQUIRED_ENV = (
    "CB_CREDENTIAL_CAPABILITY_SECRET",
    "CB_CREDENTIAL_BROKER_AUDIENCE",
    "CB_BROKER_GRANT_DB_PATH",
    "CB_BROKER_GRANT_KEK_HEX",
    "CB_CREDENTIAL_NONCE_DB_PATH",
    "CB_BROKER_IDEMPOTENCY_DB_PATH",
)

# Removed broker runtime configuration that must not reappear.
BROKER_OBSOLETE_ENV = (
    "CB_BROKER_SHARED_SECRET",
    "CB_VAULT_EMAIL",
    "CB_VAULT_PASSWORD",
)

# Still-required broker runtime configuration that must survive edits.
BROKER_KEEP_ENV = (
    "CB_BROKER_SUBMIT_SECRET",
    "CB_VAULT_BASE_URL",
)


def _qualification_script() -> str:
    """Return the run script of the 'Qualify published image' step."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    step_index = next(
        i for i, line in enumerate(lines) if line.strip() == f"- name: {QUALIFICATION_STEP}"
    )
    run_index = next(
        i for i in range(step_index, len(lines)) if lines[i].strip() == "run: |"
    )
    script_lines: list[str] = []
    for line in lines[run_index + 1 :]:
        if not line.strip():
            continue
        if line.startswith("          "):
            script_lines.append(line[10:])
            continue
        break
    script = "\n".join(script_lines)
    assert "docker create" in script, "qualification step has no docker create"
    return script


def _qualification_env(script: str) -> dict[str, str]:
    return dict(re.findall(r"--env\s+(CB_[A-Z0-9_]+)=(\S+)", script))


def test_qualification_runs_broker_env_for_credential_broker_service_only() -> None:
    script = _qualification_script()
    # Broker-only variables must be guarded so every other matrix service
    # (router, viewer, identity-link, ...) is not handed broker grant state.
    assert 'SERVICE" = credential-broker' in script or (
        '${SERVICE} == "credential-broker"' in script
    ), "broker env must be conditional on SERVICE == credential-broker"
    assert "broker_args=(" in script, "broker env must be collected into a guarded arg array"


def test_qualification_provides_broker_runtime_required_env() -> None:
    script = _qualification_script()
    env = _qualification_env(script)
    for name in BROKER_REQUIRED_ENV:
        assert name in env, f"qualification step missing broker env: {name}"
        assert env[name], f"qualification step sets empty broker env: {name}"


def test_qualification_keeps_other_matrix_services_free_of_broker_env() -> None:
    script = _qualification_script()
    common_create = script.split("docker create", 1)[1].split("cleanup()", 1)[0]
    assert "--env CB_BROKER_" not in common_create
    assert "--env CB_VAULT_" not in common_create


def test_qualification_grant_custody_db_path_is_versioned() -> None:
    script = _qualification_script()
    grant_db = _qualification_env(script).get("CB_BROKER_GRANT_DB_PATH", "")
    assert grant_db == "/data/state/grant-custody-v1.sqlite3", (
        "grant custody DB must live at /data/state/grant-custody-v1.sqlite3"
    )


def test_qualification_provides_writable_state_path() -> None:
    script = _qualification_script()
    # The broker creates grant-custody-v1.sqlite3 plus nonce/idempotency DBs
    # under /data/state at startup; the qualification container must mount a
    # writable state path rather than relying on image layers.
    assert "--mount" in script and "tmpfs" in script, (
        "qualification step must mount a writable /data/state (tmpfs)"
    )


def test_qualification_grant_kek_is_qualification_dummy_not_live_secret() -> None:
    script = _qualification_script()
    kek = _qualification_env(script).get("CB_BROKER_GRANT_KEK_HEX", "")
    assert re.fullmatch(r"[0-9a-f]{64}", kek), (
        "CB_BROKER_GRANT_KEK_HEX must be a 64-hex-char (32-byte) key"
    )
    assert kek not in ("0" * 64, "f" * 64), (
        "qualification KEK must not be an all-zeroes/all-f dummy"
    )


def test_qualification_drops_obsolete_broker_env() -> None:
    script = _qualification_script()
    for name in BROKER_OBSOLETE_ENV:
        assert name not in script, f"obsolete broker env still set: {name}"


def test_qualification_keeps_still_required_broker_env() -> None:
    script = _qualification_script()
    env = _qualification_env(script)
    for name in BROKER_KEEP_ENV:
        assert name in env, f"still-required broker env missing: {name}"
        assert env[name], f"still-required broker env empty: {name}"


def test_qualification_broker_capability_secret_is_long_enough() -> None:
    script = _qualification_script()
    secret = _qualification_env(script).get("CB_CREDENTIAL_CAPABILITY_SECRET", "")
    assert len(secret.encode("utf-8")) >= 16, (
        "CB_CREDENTIAL_CAPABILITY_SECRET must be at least 16 bytes"
    )
