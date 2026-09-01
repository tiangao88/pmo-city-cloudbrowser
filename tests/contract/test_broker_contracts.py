from cloudbrowser.credential_broker import BrokerResult, LoginIntent, SiteDeclaration


def test_site_declaration_requires_exact_origin():
    declaration = SiteDeclaration(
        site_id="example",
        origin="https://login.example.test",
        redirect_origins=("https://app.example.test",),
    )
    assert declaration.allows("https://login.example.test/start")
    assert declaration.allows("https://app.example.test/callback")
    assert not declaration.allows("https://evil.example.test/callback")
    assert not declaration.allows("https://login.example.test.evil.test/")


def test_broker_result_is_status_only_and_bounded():
    result = BrokerResult("req-1", "authenticated", duration_ms=12)
    assert result.to_public_dict() == {
        "request_id": "req-1",
        "status": "authenticated",
        "error_code": None,
        "duration_ms": 12,
    }


def test_broker_result_rejects_unknown_status():
    try:
        BrokerResult("req-1", "secret-returned")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown status was accepted")
