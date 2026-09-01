from cloudbrowser.security.policy import BROKER_STATUS_VALUES, FORBIDDEN_AGENT_CAPABILITIES


def test_broker_status_is_bounded_and_non_material():
    assert BROKER_STATUS_VALUES == {
        "authenticated",
        "mfa_required",
        "failed",
        "not_shared",
        "unsupported",
    }
    assert not BROKER_STATUS_VALUES & FORBIDDEN_AGENT_CAPABILITIES


def test_agent_forbidden_capabilities_include_sensitive_paths():
    required = {
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
    assert required <= FORBIDDEN_AGENT_CAPABILITIES
