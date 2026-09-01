from cloudbrowser.credential_broker import BrokerResult, LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.service import BrokerService, ResolvedBinding


def as_result(value: BrokerResult | SiteDeclaration) -> BrokerResult:
    assert isinstance(value, BrokerResult)
    return value


def test_broker_rejects_caller_binding_change():
    intent = LoginIntent("req-1", "profile-a", "principal-a", "browser-a", "site-a", "user-ref")
    service = BrokerService(
        lambda _: ResolvedBinding("profile-a", "principal-other", "browser-a", "site-a", "g1"),
        {"site-a": SiteDeclaration("site-a", "https://login.example.test")},
    )
    result = as_result(service.validate_intent(intent))
    assert result.status == "failed"
    assert result.error_code == "binding_mismatch"


def test_broker_returns_unsupported_for_undeclared_site():
    intent = LoginIntent("req-2", "profile-a", "principal-a", "browser-a", "site-x", "user-ref")
    service = BrokerService(
        lambda _: ResolvedBinding("profile-a", "principal-a", "browser-a", "site-x", "g1"),
        {},
    )
    result = as_result(service.validate_intent(intent))
    assert result.status == "unsupported"
    assert result.error_code == "site_not_declared"


def test_broker_returns_declaration_for_valid_binding():
    intent = LoginIntent("req-3", "profile-a", "principal-a", "browser-a", "site-a", "user-ref")
    declaration = SiteDeclaration("site-a", "https://login.example.test")
    service = BrokerService(
        lambda _: ResolvedBinding("profile-a", "principal-a", "browser-a", "site-a", "g1"),
        {"site-a": declaration},
    )
    assert service.validate_intent(intent) == declaration
