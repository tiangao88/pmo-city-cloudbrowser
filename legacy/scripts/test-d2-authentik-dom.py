#!/usr/bin/env python3
"""Static D2 regression for exact Authentik 2025.8.1 shadow-DOM safety."""
import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("CB_SLOT_SCRIPTS", str(HERE))
os.environ.setdefault("SSO_BROKER_ENABLED", "true")
path = HERE / "sso-broker.py"
spec = importlib.util.spec_from_file_location("sso_broker_under_test", path)
sb = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(sb)

probe = sb.TOTP_PROBE_JS
fill = sb.TOTP_FILL_JS
pick = sb.TOTP_PICK_JS
ident = sb.FILL_JS

# Exact 2025.8.1 nesting:
# executor SR -> validate host SR -> validate-code host SR.
for js in (probe, fill):
    assert "ak-stage-authenticator-validate'" in js, "missing validate host"
    assert "deviceClass" in js and "totp" in js, "must require exact totp"
    assert "ak-stage-authenticator-validate-code" in js, "missing code host"

# Picker selection must use the challenge object, not translated button text.
assert "deviceChallenges" in pick and "deviceClass" in pick and "totp" in pick
assert "traditional authenticator" not in pick.lower()
assert "code-based" not in pick.lower()

# Identification password lives inside ak-flow-input-password's shadow root.
assert "ak-flow-input-password" in ident
assert "querySelector('input[name=password]')" in ident

print("PASS Authentik 2025.8.1 exact DOM + deviceClass=TOTP guards")
