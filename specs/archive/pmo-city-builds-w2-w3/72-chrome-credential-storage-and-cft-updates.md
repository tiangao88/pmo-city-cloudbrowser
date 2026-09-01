# 72 — Embedded Chrome credential-storage ban and CfT customization contract

Date: 2026-08-25  
Status: **IMPLEMENTED — LIVE CANARY VERIFIED; ACTIVE SLOT POLICY STAGED**

## Security directive

The CloudBrowser embedded Chrome is never a credential vault. Vaultwarden and
the deterministic GrantHub/broker are the only supported credential store and
fill mechanism.

The embedded browser therefore MUST:

1. never offer to save a password;
2. never save a newly entered password;
3. purge any legacy Chrome `Login Data*` files before launch; Chrome may
   recreate empty database shells while running, but their `logins` tables
   must stay empty;
4. never offer or retain address or payment-card autofill data;
5. re-apply these controls before every Chrome launch, including the first
   launch after a Chrome for Testing (CfT) binary update;
6. fail closed — Chrome must not start if the mandatory policy, customizer, or
   tab-bar extension manifest is absent or invalid.

`NEKO_PASSWORD_ADMIN` is unrelated infrastructure authentication and is not a
Chrome-saved credential. D1 separately retires the static neko *user* password.

## Root cause / previous gap

The slot wrapper previously modified only two profile preferences
(`restore_on_startup` and Translate) and then executed a version-hardcoded path
(`/home/neko/.config/cft-chrome-128/chrome`). `slot-policy-init.sh` modified
only `/etc/opt/chrome/policies/managed/policies.json`.

Official CfT reads `/etc/opt/chrome_for_testing/policies`, so the fleet had no
positive, testable CfT policy preventing password storage. Updating the binary
could also leave the launch wrapper and its version-specific path stale. There
was no customization receipt tying the prepared profile to the actual browser
and tab-bar versions.

## Locked design

### Managed policy (primary enforcement)

At every container boot, `slot-policy-init.sh` installs the same
`pmo-city-security.json` into both official policy roots:

- `/etc/opt/chrome/policies/managed/`
- `/etc/opt/chrome_for_testing/policies/managed/`

Mandatory values:

```json
{
  "PasswordManagerEnabled": false,
  "AutofillAddressEnabled": false,
  "AutofillCreditCardEnabled": false,
  "PasswordLeakDetectionEnabled": false,
  "PDFViewerEnabled": false,
  "TranslateEnabled": false
}
```

The password-manager policy is authoritative: users cannot save new passwords.
The legacy profile preferences below are defense in depth and suppress the UI
before/while managed policy initializes.

### Every-launch customizer (defense in depth + update hook)

Before Chrome starts, `chrome-customize.py prepare-profile`:

- validates the CfT managed policy and every required value;
- validates the unpacked tab-bar `manifest.json` and version;
- sets `credentials_enable_service=false` and
  `credentials_enable_autosignin=false`;
- sets `profile.password_manager_enabled=false`;
- disables address and card autofill preferences;
- keeps `session.restore_on_startup=5` and Translate disabled on fleet slots;
- lets the retained W1 reference viewer explicitly request
  `--restore-mode last-session`, preserving its existing D5 session behavior;
- deletes every `Login Data*` file from the stopped profile;
- writes `.pmo-city-customization.json` with the actual CfT version,
  extension version, policy digest and applied customization set.

The wrapper runs under `set -e`: validation failure prevents Chrome startup.

### Version-independent CfT selection

Both the fleet slot wrapper and retained W1 reference-viewer wrapper no longer
execute a hardcoded `cft-chrome-128` path. Selection is:

1. explicit `CFT_CHROME_BIN`, when provided;
2. a versionless `cft-chrome-current/chrome` path under the wrapper's CfT root
   (the update contract: stage a new verified build, then atomically repoint the
   symlink);
3. backward-compatible discovery of existing `cft-chrome-*/chrome` installs.

Regardless of which binary is selected, its real `--version` output is passed
to the customizer before `exec`. A version update therefore cannot bypass the
full PMO City customization pass.

## CfT update runbook / acceptance gate

A CfT update is complete only after all of the following:

1. Stage the verified CfT build without changing the current symlink.
2. Run CDP/browser-use compatibility tests against the staged binary.
3. Atomically repoint `cft-chrome-current` (or set `CFT_CHROME_BIN`).
4. Restart one idle slot; never interrupt a live human slot.
5. Require `slot-policy-init-ok` and `chrome-customize: profile ready`.
6. Verify the receipt names the new browser version and current extension.
7. Verify effective managed policy through Chrome's policy service/CDP.
8. Verify any recreated `Login Data*` databases have zero saved-login rows and
   the password save UI is unavailable.
9. Run tab bar, kiosk geometry, downloads-only PDF, CDP attach/navigation and
   session snapshot/restore smoke tests.
10. Roll the second slot only after the first slot is green.

An update that only replaces the CfT executable is **not deployed**.

## Regression tests

`test-chrome-customization.py` covers:

- managed policy installation for stock Chrome and official CfT;
- password manager + autofill disabled values;
- defense-in-depth profile preferences;
- deletion of legacy `Login Data`;
- customization receipt refresh on browser-version change;
- no hardcoded CfT version in the launch wrapper;
- fail-closed policy-init ordering before Chrome launch.

## Deployment checklist

- [x] Spec written.
- [x] Tests written RED first and observed failing.
- [x] Central customizer implemented.
- [x] Slot policy-init made dual-root and fail-closed.
- [x] Slot wrapper made version-independent and every-launch.
- [x] Local regression tests green.
- [x] Deploy shared scripts volume.
- [x] Restart idle slot-2 canary.
- [x] Verify effective live policy, preferences, receipt and zero saved-login rows.
- [x] Verify slot-2 CDP health and slot-1 policy staging without interrupting its active user.
- [ ] Restart slot-1 after montigaud's active session naturally ends; the next launch automatically runs the same customizer.
- [x] Apply the same fail-closed gate to the retained W1 reference viewer.
- [x] Add viewer-path regression coverage (8/8 total Spec-72 tests).
- [x] Commit and push evidence.

## Live evidence (2026-08-25)

- Shared-volume hashes matched the canonical repo copies for the customizer,
  wrapper, policy init and restart API.
- Slot-2 was idle and used as the restart canary. `slot-policy-init` installed
  both official policy roots; Chrome then logged `chrome-customize: profile
  ready` before DevTools started.
- Slot-2 effective state: CfT `128.0.6613.137`; tab-bar `1.13.1`;
  `PasswordManagerEnabled=false`; address/card autofill false; preference
  defenses false; saved-login rows `0`; Chrome RUNNING; CDP healthy.
- Slot-1 was actively assigned to montigaud with three work tabs. It was not
  restarted. The dual-root managed policy was safely installed and its ready
  marker verified while Chrome kept running. At the next natural Chrome
  launch, the version-independent wrapper will apply the profile customizer
  and receipt before exec.
- Full router regression suite: `114/114` passed. Tab snapshot tests: `3/3`.
  Spec-72 customization tests: `6/6`.

## Sources

- Chrome Enterprise `PasswordManagerEnabled`: disabled means users cannot save
  new passwords (previously saved passwords are handled here by purge).
- Chromium enterprise policy documentation: official Chrome uses
  `/etc/opt/chrome/policies`; official Chrome for Testing uses
  `/etc/opt/chrome_for_testing/policies`.
