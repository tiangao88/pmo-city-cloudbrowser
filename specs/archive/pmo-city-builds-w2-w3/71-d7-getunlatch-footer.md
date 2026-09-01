# 71 — D7 Getunlatch CRM footer re-check as montigaud (2026-08-25)

Status: **DONE — LIVE VERIFIED**

## Objective

Close W2 D7 by re-checking the Getunlatch CRM footer after a real login on the
current fleet, without the historical F11/90% zoom workaround, and under
montigaud's own per-user Vaultwarden/GrantHub identity.

## Identity and credential path

- Router assignment at test time: `montigaud@aikumi.pro` → slot-1.
- `/connect/status`: `shared=true`, `session=true`, `usable=true`,
  `revoked=false`.
- A slot-local deterministic probe unwrapped montigaud's grant, minted a vault
  access session, synced the vault and found **exactly one** Getunlatch item.
- Its login fields were decrypted and injected inside the slot process. No key,
  token, username or password was printed or returned to the agent context.
- Login reached the canonical read-only CRM surface:
  `https://alsei-residentiel.getunlatch.com/admin/re-purchases/?mode=CRM`.

This proves the operation used montigaud's own usable grant and not the retired
shared spike-user fallback.

## Live footer evidence

The authenticated page reported:

```json
{
  "title": "CRM - ALSEI RESIDENTIEL",
  "url_path": "/admin/re-purchases/",
  "text": "Lignes par page : 25\n1 - 25 sur 27678",
  "viewport": {"w": 1280, "h": 720, "dpr": 1},
  "rect": {"x": 64, "y": 672, "w": 1200, "h": 48, "bottom": 720},
  "fullyVisible": true,
  "nearbyButtons": 5,
  "zoom": 1
}
```

## Verdict

**PASS.** The complete CRM footer and pagination controls are visible at the
native 100% zoom in the kiosk's 1280×720 viewport. The footer's bottom is
exactly aligned with the viewport bottom (`720`) and is not clipped. No F11 or
90% zoom workaround is required.

The current total (`27678`) differs from the 2026-08-17 observation (`27667`)
because the live CRM dataset changed; it is not a layout regression.

## Side effects and hygiene

- The test was read-only in Getunlatch: login and visual/DOM inspection only.
- No CRM record, filter or setting was changed.
- The login reused an existing restored tab, preserving the three-tab cap.
- The resulting kiosk workspace contains the CRM, Agentic PMO and Exa tabs.
