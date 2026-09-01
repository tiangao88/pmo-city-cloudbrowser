#!/usr/bin/env python3
"""D15 Phase B/C regression: exact cookie, identity and re-login safety."""
import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("CB_SLOT_SCRIPTS", str(HERE))
os.environ.setdefault("SSO_BROKER_ENABLED", "true")
os.environ.setdefault("SSO_SESSION_CHECK_S", "300")
os.environ.setdefault("SSO_SESSION_RELOGIN_BEFORE_S", "900")
os.environ.setdefault("SSO_SESSION_COOKIE_NAME", "tinyauth-session-39fcd0f6")
os.environ.setdefault(
    "SSO_SESSION_PROBE_ORIGINS",
    "https://pmo.city,https://cloudbrowser.dev01.pmo.city,https://cloudfiles.dev01.pmo.city",
)
path = Path(os.environ.get("SSO_BROKER", HERE / "sso-broker.py"))
spec = importlib.util.spec_from_file_location("sso_broker_d15", path)
sb = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(sb)

NOW = 1_800_000_000.0
COOKIE = sb.SESSION_COOKIE_NAME
OWNER_A = "owner-a@aikumi.pro"
OWNER_B = "owner-b@aikumi.pro"


def cookie(expires, **overrides):
    value = {
        "domain": ".pmo.city",
        "name": COOKIE,
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "expires": expires,
    }
    value.update(overrides)
    return value


class FakeCDP:
    def __init__(self, cookies=None, response=None, browser_network_error=False):
        self.cookies = cookies or []
        self.response = response
        self.browser_network_error = browser_network_error
        self.calls = []

    def cmd(self, method, *args, **kwargs):
        self.calls.append((method, kwargs))
        if self.browser_network_error and method == "Network.getAllCookies":
            return {"error": {"code": -32601, "message": "Method not found"}}
        if self.response is not None:
            return self.response
        assert method == "Storage.getCookies"
        assert not kwargs.get("session")
        return {"result": {"cookies": self.cookies}}


def health(cookies):
    return sb.session_cookie_health(FakeCDP(cookies), now=NOW)


# Browser-level Chrome 128 rejects Network.getAllCookies; the broker must use
# Storage.getCookies for browser-level reads rather than misclassify health.
h = health([cookie(NOW + 3600)])
assert h["status"] == "healthy"
probe = FakeCDP([cookie(NOW + 3600)], browser_network_error=True)
assert sb.session_cookie_health(probe, now=NOW)["status"] == "healthy"
assert [m for m, _ in probe.calls] == ["Storage.getCookies"]

# Unrelated and lookalike cookies must not count as an SSO session.
h = health([cookie(NOW + 9999, name="analytics")])
assert h["status"] == "missing" and not h["valid"]
for forged in (
    cookie(NOW + 3600, name=COOKIE + "-forged"),
    cookie(NOW + 3600, domain="cloudfiles.dev01.pmo.city"),
    cookie(NOW + 3600, domain=".evilpmo.city"),
    cookie(NOW + 3600, path="/app"),
    cookie(NOW + 3600, secure=False),
    cookie(NOW + 3600, httpOnly=False),
):
    assert health([forged])["status"] == "missing"

# Exactly one persistent, secure, HttpOnly cookie at .pmo.city:/ is accepted.
h = health([cookie(NOW + 3600)])
assert h["status"] == "healthy" and h["valid"] and not h["refresh_needed"]
assert 3599 <= h["ttl_s"] <= 3601

# Expiry validity is distinct from proactive refresh policy.
h = health([cookie(NOW + 600)])
assert h["status"] == "expiring" and h["valid"] and h["refresh_needed"]
h = health([cookie(NOW - 1)])
assert h["status"] == "expired" and not h["valid"] and h["refresh_needed"]
h = health([cookie(0)])
assert h["status"] == "session-only" and not h["valid"] and h["refresh_needed"]

# Ambiguous exact duplicates fail closed; a forged long-lived prefix cannot mask
# the expired exact cookie.
h = health([cookie(NOW + 3600), cookie(NOW + 7200)])
assert h["status"] == "ambiguous" and not h["valid"] and not h["relogin"]
h = health([cookie(NOW - 1), cookie(NOW + 99999, name=COOKIE + "-forged")])
assert h["status"] == "expired" and not h["valid"]

# Returned CDP protocol errors/malformed payloads are telemetry errors, never a
# missing-cookie re-login trigger.
for response in (
    {"error": {"code": -32601, "message": "Method not found"}},
    {},
    {"result": {}},
    {"result": {"cookies": {}}},
):
    h = sb.session_cookie_health(FakeCDP(response=response), now=NOW)
    assert h["status"] == "error" and not h["relogin"]


class ReloginCDP:
    def __init__(self, cookies=None, attach_ok=True, delete_error=False, reload_error=False):
        self.cookies = cookies or [cookie(NOW + 600)]
        self.attach_ok = attach_ok
        self.delete_error = delete_error
        self.reload_error = reload_error
        self.calls = []

    def cmd(self, method, params=None, **kwargs):
        self.calls.append((method, params, kwargs))
        if method == "Network.getAllCookies":
            assert kwargs.get("session") == "sid-1"
            return {"result": {"cookies": self.cookies}}
        if method == "Network.deleteCookies" and self.delete_error:
            return {"error": {"message": "delete failed"}}
        if method == "Page.reload" and self.reload_error:
            return {"error": {"message": "reload failed"}}
        return {"result": {}}


app = {"type": "page", "targetId": "app", "url": "https://cloudfiles.dev01.pmo.city/files"}
original_attach = sb.attach_page
try:
    # Attach is proven before deletion; only the exact cookie is removed, then
    # the same tab reloads. No tab is created or evicted.
    rc = ReloginCDP()
    sb.attach_page = lambda cdp, target_id: (cdp.calls.append(("ATTACH", target_id, {})) or
                                             ("sid-1" if cdp.attach_ok else None))
    assert sb.request_session_relogin(rc, app)
    methods = [c[0] for c in rc.calls]
    assert methods.index("ATTACH") < methods.index("Network.deleteCookies")
    assert methods.index("Network.deleteCookies") < methods.index("Page.reload")
    assert any(
        c[0] == "Network.getAllCookies" and c[2].get("session") == "sid-1"
        for c in rc.calls
    )
    deletes = [c for c in rc.calls if c[0] == "Network.deleteCookies"]
    assert len(deletes) == 1 and deletes[0][1] == {
        "name": COOKIE, "domain": ".pmo.city", "path": "/"
    }
    assert any(c[0] == "Page.reload" and c[2].get("session") == "sid-1" for c in rc.calls)

    # Attach failure leaves authentication intact.
    rc = ReloginCDP(attach_ok=False)
    assert not sb.request_session_relogin(rc, app)
    assert not any(c[0] == "Network.deleteCookies" for c in rc.calls)

    # Ambiguity/protocol/delete failures never reload or partially delete.
    for rc in (
        ReloginCDP(cookies=[cookie(NOW + 600), cookie(NOW + 700)]),
        ReloginCDP(delete_error=True),
    ):
        assert not sb.request_session_relogin(rc, app)
        assert not any(c[0] == "Page.reload" for c in rc.calls)
finally:
    sb.attach_page = original_attach

# Target allowlist is explicit, not every attacker-controlled *.pmo.city host.
for good in (
    "https://pmo.city/",
    "https://cloudbrowser.dev01.pmo.city/",
    "https://cloudfiles.dev01.pmo.city/files",
):
    assert sb.is_session_probe_url(good)
for bad in (
    "https://auth.pmo.city/",
    "https://secrets.pmo.city/",
    "https://evil.pmo.city/",
    "https://evilpmo.city/",
    "http://cloudfiles.dev01.pmo.city/",
    "chrome-extension://abc/page.html",
    "https://user:pass@cloudfiles.dev01.pmo.city/",
):
    assert not sb.is_session_probe_url(bad)

# Owner/generation transitions reset all D15 scheduling state, including a
# same-email reassignment with a new marker timestamp.
state = {"last_session_check": 123.0, "last_session_status": "healthy", "last_relogin_request": 122.0,
         "session_generation": (OWNER_A, 1, 1.0)}
sb.reset_session_state(state, (OWNER_B, 1, 2.0))
assert state == {"last_session_check": 0.0, "last_session_status": None,
                 "last_relogin_request": 0.0, "session_generation": (OWNER_B, 1, 2.0),
                 "owner_refresh_required": True}
state.update({"last_session_check": 321.0, "last_session_status": "healthy", "last_relogin_request": 320.0})
sb.reset_session_state(state, (OWNER_B, 1, 3.0))
assert state["last_session_check"] == state["last_relogin_request"] == 0.0
assert state["last_session_status"] is None and state["session_generation"] == (OWNER_B, 1, 3.0)

# Login completion requires a fresh exact cookie and the trusted app identity
# endpoint to confirm the canonical slot owner. An unchanged stale cookie or
# mismatched owner is rejected.
old = cookie(NOW + 3600)
new = cookie(NOW + 7200)
old["value"] = "old"
new["value"] = "new"
assert sb.fresh_cookie_issued(old, new)
assert not sb.fresh_cookie_issued(old, dict(old))
assert sb.session_identity_matches({"status": 200, "auth": {"authenticated": True, "email": OWNER_A}}, OWNER_A)
assert not sb.session_identity_matches({"status": 200, "auth": {"authenticated": True, "email": OWNER_A}}, OWNER_B)

# Integrated post-login gate: unchanged cookie and owner mismatch are rejected;
# only a fresh exact cookie validated by TinyAuth for the canonical owner passes.
class PostLoginCDP:
    def __init__(self, after):
        self.after = after
    def cmd(self, method, *args, **kwargs):
        assert method == "Storage.getCookies"
        assert not kwargs.get("session")
        return {"result": {"cookies": [self.after]}}

original_probe = sb.probe_session_identity
original_log = sb.log
original_fill = sb.fill_and_submit
original_validate = sb.validate_session_after_login
try:
    sb.log = lambda msg: None
    sb.probe_session_identity = lambda c, session=None: {
        "status": 200, "auth": {"authenticated": True, "email": OWNER_A}}
    old_same_value = dict(old)
    old_same_value["expires"] = NOW + 99999
    assert not sb.validate_session_after_login(PostLoginCDP(old_same_value), OWNER_A, old)
    assert sb.validate_session_after_login(PostLoginCDP(new), OWNER_A, old)
    assert not sb.validate_session_after_login(PostLoginCDP(new), OWNER_B, old)

    # Direct completion must revalidate the immutable assignment generation.
    sb.fill_and_submit = lambda cdp, target: True
    sb.validate_session_after_login = lambda cdp, owner, before: True
    calls = []
    assert not sb.handle_login(PostLoginCDP(new), {}, OWNER_A, [NOW],
                               generation=(OWNER_A, 1, 1.0),
                               revalidate=lambda: (calls.append(1) or False),
                               before_cookie=old)
    assert calls == [1]
finally:
    sb.probe_session_identity = original_probe
    sb.log = original_log
    sb.fill_and_submit = original_fill
    sb.validate_session_after_login = original_validate

print("PASS D15 exact-cookie + owner-bound session health policy")
