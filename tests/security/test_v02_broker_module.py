import cloudbrowser.credential_broker as broker


def test_credential_broker_exports_status_values():
    assert broker.BROKER_STATUS_VALUES == {
        "authenticated",
        "mfa_required",
        "failed",
        "not_shared",
        "unsupported",
    }


def test_broker_module_has_no_vault_client_import():
    assert "vault" not in broker.__file__.lower()
