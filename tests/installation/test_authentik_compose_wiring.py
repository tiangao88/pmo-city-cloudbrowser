"""Compose wiring for the exact-target Authentik policy."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from cloudbrowser.security.policy import validate_deadline_policy

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = ROOT / "deploy" / "coolify"
FILES = ("compose.yaml", "compose.coolify.yaml")
COOLIFY_SECRET_NAMES = (
    "SERVICE_PASSWORD_64_AGENTCTRLSECRET",
    "SERVICE_PASSWORD_64_BROKERSUBMIT",
    "SERVICE_PASSWORD_64_CREDENTIALCAPSECRET",
    "SERVICE_PASSWORD_64_DLSECRET",
    "SERVICE_PASSWORD_64_IDLINKSECRET",
    "SERVICE_PASSWORD_64_INGESTSECRET",
    "SERVICE_PASSWORD_64_ROUTERSECRET",
    "SERVICE_PASSWORD_64_VIEWERSECRET",
)
POLICY_KEYS = (
    "CB_BROKER_ADAPTER",
    "CB_BROKER_SSO_ENTRY_URL",
    "CB_BROKER_SSO_IDP_ORIGINS",
    "CB_BROKER_SSO_CALLBACK_ORIGINS",
    "CB_BROKER_SSO_APPLICATION_ORIGINS",
    "CB_BROKER_SSO_SUCCESS_PATHS",
    "CB_BROKER_SSO_ALLOWED_MFA",
    "CB_BROKER_SSO_IDENTITY_SELECTOR",
    "CB_BROKER_SSO_IDENTITY_CLAIM",
    "CB_BROKER_SSO_STAGE_TIMEOUT_S",
)


def _service_block(filename: str, service: str) -> str:
    lines = (COMPOSE_DIR / filename).read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {service}:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break
        block.append(line)
    return "\n".join(block)


def _value(block: str, key: str) -> str:
    prefix = f"      {key}: "
    matches = [line.removeprefix(prefix) for line in block.splitlines() if line.startswith(prefix)]
    assert len(matches) == 1, (key, matches)
    return matches[0]


def _compose_command() -> list[str]:
    docker = shutil.which("docker")
    if docker:
        probe = subprocess.run(
            [docker, "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            return [docker, "compose"]
    standalone = shutil.which("docker-compose")
    if standalone:
        return [standalone]
    pytest.skip("Docker Compose CLI is not installed")


def _required_variables(filename: str) -> set[str]:
    text = (COMPOSE_DIR / filename).read_text(encoding="utf-8")
    return set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?[^}]+\}", text))


def _complete_fake_env(filename: str) -> dict[str, str]:
    env = {
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "PATH": os.environ.get("PATH", ""),
    }
    env.update({name: "x" * 64 for name in _required_variables(filename)})
    env.update({name: "x" * 64 for name in COOLIFY_SECRET_NAMES})
    env.update(
        {
            "CB_AGENT_CONTROL_URLS": "slot-1=http://agent-control:8090",
            "CB_BINDING_GENERATION": "generation-test-g1",
            "CB_BROKER_GRANT_KEK_HEX": "ab" * 32,
            "CB_BROKER_ORIGIN": "https://example.test",
            "CB_BROKER_SITE_ID": "site-test",
            "CB_BROKER_SUCCESS_PATH": "/success",
            "CB_BROWSER_ID": "browser-test",
            "CB_INSTANCE_ID": "cloudbrowser-test",
            "CB_OIDC_ISSUER": "https://auth.example.test/",
            "CB_PRINCIPAL_ID": "principal-test",
            "CB_RELEASE_VERSION": "test-release",
            "CB_SLOT_SUPERVISOR_URLS": "slot-1=http://slot-supervisor:8081",
            "CB_TINYAUTH_REALM": "test-realm",
            "CB_VAULT_BASE_URL": "https://vault.example.test",
        }
    )
    return env


def _render_compose(filename: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_compose_command(), "-f", str(COMPOSE_DIR / filename), "config"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _rendered_values(rendered: str, key: str) -> set[str]:
    return {
        value.strip('"')
        for value in re.findall(rf"^\s+{re.escape(key)}:\s+(.+)$", rendered, re.MULTILINE)
    }


def test_both_compose_variants_wire_identical_policy_to_browser_and_broker() -> None:
    for filename in FILES:
        browser = _service_block(filename, "browser")
        broker = _service_block(filename, "credential-broker")
        for key in POLICY_KEYS:
            assert _value(browser, key).replace(":?CB_BROKER_ADAPTER is required (basic or sso)", ":-basic") == _value(broker, key), (filename, key)


def test_router_deadline_wiring_covers_stage_and_stays_within_capability_ttl() -> None:
    for filename in FILES:
        router = _service_block(filename, "router")
        assert _value(router, "CB_CREDENTIAL_BROKER_TIMEOUT_S") == "${CB_CREDENTIAL_BROKER_TIMEOUT_S:-25}"
        assert _value(router, "CB_CREDENTIAL_CAPABILITY_TTL_S") == "${CB_CREDENTIAL_CAPABILITY_TTL_S:-26}"


def test_rendered_compose_defaults_satisfy_deadline_policy() -> None:
    for filename in FILES:
        text = (COMPOSE_DIR / filename).read_text(encoding="utf-8")
        timeout_match = re.search(r"CB_CREDENTIAL_BROKER_TIMEOUT_S: \$\{[^}]+:-([0-9.]+)\}", text)
        ttl_match = re.search(r"CB_CREDENTIAL_CAPABILITY_TTL_S: \$\{[^}]+:-([0-9.]+)\}", text)
        stage_match = re.search(r"CB_BROKER_SSO_STAGE_TIMEOUT_S: \$\{[^}]+:-([0-9.]+)\}", text)
        assert timeout_match and ttl_match and stage_match
        timeout = float(timeout_match.group(1))
        ttl = float(ttl_match.group(1))
        stage = float(stage_match.group(1))
        validate_deadline_policy(ttl_s=ttl, outer_timeout_s=timeout, stage_timeout_s=stage)


def test_coolify_security_secrets_are_strict_substitutions() -> None:
    text = (COMPOSE_DIR / "compose.coolify.yaml").read_text(encoding="utf-8")
    for name in (
        "SERVICE_PASSWORD_64_ROUTERSECRET",
        "SERVICE_PASSWORD_64_CREDENTIALCAPSECRET",
        "SERVICE_PASSWORD_64_BROKERSUBMIT",
    ):
        assert re.search(rf"\$\{{{name}:\?[^}}]+\}}", text), name


def test_coolify_compose_requires_every_magic_secret() -> None:
    text = (COMPOSE_DIR / "compose.coolify.yaml").read_text(encoding="utf-8")
    references = re.findall(r"\$\{(SERVICE_PASSWORD_64_[A-Z0-9_]+)([^}]*)\}", text)
    assert {name for name, _ in references} == set(COOLIFY_SECRET_NAMES)
    assert all(
        suffix == f":?{name} is required" for name, suffix in references
    ), references


@pytest.mark.parametrize("filename", FILES)
def test_compose_renders_with_complete_fake_environment_and_expected_defaults(
    filename: str,
) -> None:
    result = _render_compose(filename, _complete_fake_env(filename))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _rendered_values(result.stdout, "CB_CREDENTIAL_BROKER_TIMEOUT_S") == {"25"}
    assert _rendered_values(result.stdout, "CB_CREDENTIAL_CAPABILITY_TTL_S") == {"26"}
    assert _rendered_values(result.stdout, "CB_BROKER_SSO_STAGE_TIMEOUT_S") == {"24"}
    assert _rendered_values(result.stdout, "CB_BROKER_ADAPTER") == {"basic"}


@pytest.mark.parametrize("filename", FILES)
def test_compose_render_fails_when_each_required_variable_is_omitted(filename: str) -> None:
    complete_env = _complete_fake_env(filename)
    required = _required_variables(filename)
    assert required
    for name in sorted(required):
        env = complete_env.copy()
        env.pop(name, None)
        result = _render_compose(filename, env)
        assert result.returncode != 0, f"{filename} rendered without required {name}"
        assert name in result.stderr


def test_browser_startup_fails_when_sso_policy_is_missing(monkeypatch) -> None:
    from cloudbrowser import browser_service

    monkeypatch.setenv("CB_INSTANCE_ID", "test")
    monkeypatch.setenv("CB_RELEASE_VERSION", "test")
    monkeypatch.setenv("CB_BROKER_ADAPTER", "sso")
    for key in POLICY_KEYS[1:]:
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit, match="CB_BROKER_SSO_IDP_ORIGINS is required"):
        browser_service.build_browser_service()
