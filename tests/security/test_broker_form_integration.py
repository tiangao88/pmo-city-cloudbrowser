from typing import cast

from cloudbrowser.credential_broker import AdapterResult, BrokerResult, LoginIntent, SiteDeclaration
from cloudbrowser.credential_broker.service import BrokerService, ResolvedBinding
from cloudbrowser.credential_broker.adapters import (
    CredentialMaterial,
    FormLoginAdapter,
    FormLoginDeclaration,
)


class FakeFormBrowser:
    def __init__(self, url: str, visible: set[str], account_text: str = ""):
        self.url = url
        self.visible = visible
        self.account_text = account_text
        self.calls: list[tuple[str, str, str]] = []

    def current_url(self) -> str:
        return self.url

    def fill(self, selector: str, value: str) -> None:
        self.calls.append(("fill", selector, value))

    def click(self, selector: str) -> None:
        self.calls.append(("click", selector, ""))

    def has_selector(self, selector: str) -> bool:
        return selector in self.visible

    def read_text(self, selector: str) -> str:
        assert selector == "[data-account]"
        return self.account_text


def test_form_adapter_runs_through_broker_service():
    declaration = SiteDeclaration(
        site_id="site-a",
        origin="https://login.example.test",
    )
    form_declaration = FormLoginDeclaration(
        site_id="site-a",
        origin="https://login.example.test",
        username_selector="#username",
        password_selector="#password",
        submit_selector="button[type=submit]",
        success_selector="[data-authenticated]",
        account_selector="[data-account]",
    )
    browser = FakeFormBrowser(
        "https://login.example.test/start",
        {
            "#username",
            "#password",
            "button[type=submit]",
            "[data-authenticated]",
            "[data-account]",
        },
        "alice@example.test",
    )
    intent = LoginIntent(
        request_id="req-1",
        profile_id="profile-a",
        principal_id="principal-a",
        browser_id="browser-a",
        site_id="site-a",
        username_ref="account-ref",
        binding_generation="g1",
    )
    service = BrokerService(
        lambda _: ResolvedBinding("profile-a", "principal-a", "browser-a", "site-a", "g1"),
        {"site-a": declaration},
    )

    result = service.request_login(
        intent,
        current_url="https://login.example.test/start",
        fetch_credentials=lambda ref: CredentialMaterial("alice@example.test", "pw"),
        run_adapter=lambda site, material: FormLoginAdapter().execute(
            form_declaration, cast(CredentialMaterial, material), browser
        ),
    )

    assert result == BrokerResult("req-1", "authenticated")
    assert browser.calls == [
        ("fill", "#username", "alice@example.test"),
        ("fill", "#password", "pw"),
        ("click", "button[type=submit]", ""),
    ]
