from cloudbrowser.credential_broker import AdapterResult, LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.service import BrokerService, ResolvedBinding


def make_intent(generation: str = "g1") -> LoginIntent:
    return LoginIntent(
        request_id="req-1",
        profile_id="profile-a",
        principal_id="principal-a",
        browser_id="browser-a",
        site_id="site-a",
        username_ref="account-ref",
        binding_generation=generation,
    )


def make_service(binding: ResolvedBinding | None = None) -> BrokerService:
    return BrokerService(
        lambda _: binding
        or ResolvedBinding("profile-a", "principal-a", "browser-a", "site-a", "g1"),
        {"site-a": SiteDeclaration("site-a", "https://login.example.test")},
    )


def test_stale_generation_fails_before_credential_fetch():
    fetched = []
    result = make_service().request_login(
        make_intent("old-generation"),
        current_url="https://login.example.test/start",
        fetch_credentials=lambda ref: fetched.append(ref),
        run_adapter=lambda declaration, material: AdapterResult("authenticated", True),
    )
    assert result.status == "failed"
    assert result.error_code == "stale_binding"
    assert fetched == []


def test_revoked_binding_returns_not_shared_before_credential_fetch():
    fetched = []
    binding = ResolvedBinding(
        "profile-a", "principal-a", "browser-a", "site-a", "g1", revoked=True
    )
    result = make_service(binding).request_login(
        make_intent(),
        current_url="https://login.example.test/start",
        fetch_credentials=lambda ref: fetched.append(ref),
        run_adapter=lambda declaration, material: AdapterResult("authenticated", True),
    )
    assert result.status == "not_shared"
    assert result.error_code == "grant_revoked"
    assert fetched == []


def test_authenticated_result_requires_application_identity_verification():
    credential = object()
    seen = []
    result = make_service().request_login(
        make_intent(),
        current_url="https://login.example.test/start",
        fetch_credentials=lambda ref: credential,
        run_adapter=lambda declaration, material: (
            seen.append(material) or AdapterResult("authenticated", False)
        ),
    )
    assert result.status == "failed"
    assert result.error_code == "identity_unverified"
    assert seen == [credential]


def test_public_result_does_not_include_credential_material():
    credential = object()
    result = make_service().request_login(
        LoginIntent(
            "req-2", "profile-a", "principal-a", "browser-a", "site-a", "account-ref", binding_generation="g1"
        ),
        current_url="https://login.example.test/start",
        fetch_credentials=lambda ref: credential,
        run_adapter=lambda declaration, material: AdapterResult("mfa_required", False),
    )
    public = result.to_public_dict()
    assert public["status"] == "mfa_required"
    assert credential not in public.values()
