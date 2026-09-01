from cloudbrowser.credential_broker import AdapterResult, BrokerResult
from cloudbrowser.credential_broker.adapters import (
    CredentialMaterial,
    FormLoginAdapter,
    FormLoginDeclaration,
)


class FakeFormBrowser:
    def __init__(self, url: str, visible: set[str], account_text: str = ""):
        self.url = url
        self.visible = set(visible)
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


def declaration(**overrides) -> FormLoginDeclaration:
    values = {
        "site_id": "ordinary-test",
        "origin": "https://login.example.test",
        "username_selector": "#username",
        "password_selector": "#password",
        "submit_selector": "button[type=submit]",
        "success_selector": "[data-authenticated]",
        "failure_selectors": ("[data-login-error]",),
        "account_selector": "[data-account]",
    }
    values.update(overrides)
    return FormLoginDeclaration(**values)


def credentials() -> CredentialMaterial:
    return CredentialMaterial(username="alice@example.test", password="pw")


def test_form_adapter_uses_only_declared_fields_in_order():
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
    result = FormLoginAdapter().execute(declaration(), credentials(), browser)
    assert result == AdapterResult("authenticated", True)
    assert browser.calls == [
        ("fill", "#username", "alice@example.test"),
        ("fill", "#password", "pw"),
        ("click", "button[type=submit]", ""),
    ]


def test_form_adapter_rejects_wrong_origin_before_filling():
    browser = FakeFormBrowser("https://evil.example.test/", set())
    result = FormLoginAdapter().execute(declaration(), credentials(), browser)
    assert result.status == "failed"
    assert not result.identity_verified
    assert browser.calls == []


def test_form_adapter_rejects_missing_declared_form_controls_before_filling():
    browser = FakeFormBrowser(
        "https://login.example.test/",
        {"[data-authenticated]", "[data-account]"},
        "alice@example.test",
    )
    result = FormLoginAdapter().execute(declaration(), credentials(), browser)
    assert result == AdapterResult("failed", False)
    assert browser.calls == []


def test_form_adapter_stops_on_declared_login_failure():
    browser = FakeFormBrowser(
        "https://login.example.test/",
        {
            "#username",
            "#password",
            "button[type=submit]",
            "[data-login-error]",
        },
    )
    result = FormLoginAdapter().execute(declaration(), credentials(), browser)
    assert result.status == "failed"
    assert not result.identity_verified
    assert [call[0] for call in browser.calls] == ["fill", "fill", "click"]


def test_form_adapter_reports_mfa_without_guessing():
    browser = FakeFormBrowser("https://login.example.test/", {"[data-mfa-required]"})
    result = FormLoginAdapter().execute(
        declaration(mfa_selector="[data-mfa-required]"), credentials(), browser
    )
    assert result.status == "mfa_required"
    assert not result.identity_verified


def test_form_adapter_requires_account_identity_when_declared():
    browser = FakeFormBrowser(
        "https://login.example.test/",
        {"[data-authenticated]", "[data-account]"},
        "someone-else@example.test",
    )
    result = FormLoginAdapter().execute(declaration(), credentials(), browser)
    assert result.status == "failed"
    assert not result.identity_verified


def test_form_adapter_never_returns_credential_material():
    browser = FakeFormBrowser("https://login.example.test/", set())
    result = FormLoginAdapter().execute(declaration(), credentials(), browser)
    assert result.status == "failed"
    assert not result.identity_verified
