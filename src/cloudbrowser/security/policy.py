from __future__ import annotations

BROKER_STATUS_VALUES = frozenset(
    {"authenticated", "mfa_required", "failed", "not_shared", "unsupported"}
)

FORBIDDEN_AGENT_CAPABILITIES = frozenset(
    {
        "credential_material",
        "cookie_values",
        "storage_values",
        "network_bodies",
        "authorization_headers",
        "password_values",
        "raw_cdp",
        "unrestricted_runtime_evaluate",
        "filesystem",
        "process_control",
    }
)
