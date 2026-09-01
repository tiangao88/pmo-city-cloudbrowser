import cloudbrowser.security.policy as policy


def test_policy_exports_v02_forbidden_capability_contract():
    forbidden = set(policy.FORBIDDEN_AGENT_CAPABILITIES)
    assert {
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
    } <= forbidden


def test_policy_does_not_allow_any_forbidden_capability():
    allowed = set(getattr(policy, "ALLOWED_AGENT_CAPABILITIES", ()))
    assert not allowed & set(policy.FORBIDDEN_AGENT_CAPABILITIES)
