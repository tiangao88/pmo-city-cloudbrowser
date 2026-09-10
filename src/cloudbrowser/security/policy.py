from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Mapping

BROKER_STATUS_VALUES = frozenset({"authenticated", "mfa_required", "failed", "not_shared", "unsupported"})
FORBIDDEN_AGENT_CAPABILITIES = frozenset({"credential_material", "cookie_values", "storage_values", "network_bodies", "authorization_headers", "password_values", "raw_cdp", "unrestricted_runtime_evaluate", "filesystem", "process_control"})
_DEADLINE_EPSILON_S: Final[float] = 0.001
_IDENTITY_RE = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~_-]+(?:@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*)?$")
_AUTHENTIK_POLICY_KEYS = ("CB_BROKER_SSO_ENTRY_URL", "CB_BROKER_SSO_IDP_ORIGINS", "CB_BROKER_SSO_CALLBACK_ORIGINS", "CB_BROKER_SSO_APPLICATION_ORIGINS", "CB_BROKER_SSO_SUCCESS_PATHS", "CB_BROKER_SSO_ALLOWED_MFA", "CB_BROKER_SSO_IDENTITY_SELECTOR", "CB_BROKER_SSO_IDENTITY_CLAIM", "CB_BROKER_SSO_STAGE_TIMEOUT_S")

@dataclass(frozen=True)
class AuthentikPolicy:
    entry_url: str
    idp_origins: tuple[str, ...]
    callback_origins: tuple[str, ...]
    application_origins: tuple[str, ...]
    success_paths: tuple[str, ...]
    allowed_mfa: tuple[str, ...]
    identity_selector: str
    identity_claim: str
    stage_timeout_s: float


def _csv(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in env.get(name, "").split(",") if item.strip())


def parse_authentik_policy(env: Mapping[str, str]) -> AuthentikPolicy | None:
    if env.get("CB_BROKER_ADAPTER", "").strip().lower() != "sso":
        return None
    # Preserve the startup error order used by the public contract: the IdP
    # origin is the first required security boundary after entry metadata.
    ordered = ("CB_BROKER_SSO_IDP_ORIGINS",) + tuple(name for name in _AUTHENTIK_POLICY_KEYS if name != "CB_BROKER_SSO_IDP_ORIGINS")
    missing = [name for name in ordered if not env.get(name, "").strip()]
    if missing:
        raise SystemExit(f"{missing[0]} is required when SSO is selected")
    try:
        stage_timeout_s = float(env["CB_BROKER_SSO_STAGE_TIMEOUT_S"])
    except ValueError as exc:
        raise SystemExit("CB_BROKER_SSO_STAGE_TIMEOUT_S must be a number") from exc
    if not 0 < stage_timeout_s <= 30:
        raise SystemExit("CB_BROKER_SSO_STAGE_TIMEOUT_S is invalid")
    allowed_mfa = _csv(env, "CB_BROKER_SSO_ALLOWED_MFA")
    if allowed_mfa != ("totp",):
        raise SystemExit("CB_BROKER_SSO_ALLOWED_MFA must be exactly totp")
    return AuthentikPolicy(env["CB_BROKER_SSO_ENTRY_URL"].strip(), _csv(env, "CB_BROKER_SSO_IDP_ORIGINS"), _csv(env, "CB_BROKER_SSO_CALLBACK_ORIGINS"), _csv(env, "CB_BROKER_SSO_APPLICATION_ORIGINS"), _csv(env, "CB_BROKER_SSO_SUCCESS_PATHS"), allowed_mfa, env["CB_BROKER_SSO_IDENTITY_SELECTOR"].strip(), env["CB_BROKER_SSO_IDENTITY_CLAIM"].strip(), stage_timeout_s)


def validate_deadline_policy(*, ttl_s: float, outer_timeout_s: float, stage_timeout_s: float, overhead_s: float = 0.5) -> None:
    values = (ttl_s, outer_timeout_s, stage_timeout_s, overhead_s)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values) or any(value <= 0 for value in values):
        raise ValueError("deadline values must be positive numbers")
    if not ttl_s > outer_timeout_s + _DEADLINE_EPSILON_S:
        raise ValueError("capability TTL must exceed outer timeout")
    if not outer_timeout_s > stage_timeout_s + overhead_s + _DEADLINE_EPSILON_S:
        raise ValueError("outer timeout must exceed stage timeout plus overhead")


def canonical_identity(value: object) -> str | None:
    if not isinstance(value, str) or any(ord(char) > 0x7F or (ord(char) < 0x20 and char not in " \t") or ord(char) == 0x7F for char in value):
        return None
    if "\n" in value or "\r" in value:
        return None
    candidate = value.strip().lower()
    return candidate if _IDENTITY_RE.fullmatch(candidate) and ("@" not in candidate or "." in candidate.partition("@")[2]) else None
