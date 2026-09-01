# Third-party notices

## n.eko — virtual browser viewer

- Upstream: https://github.com/m1k1o/neko
- Image in use: `ghcr.io/m1k1o/neko/google-chrome:2.9.0` (pinned, CfT 128)
- License: **Apache-2.0** — full text: https://www.apache.org/licenses/LICENSE-2.0
- No NOTICE file ships upstream (verified 2026-08-18).

### Modifications applied on top of the upstream image

Per Apache-2.0 §4(b), modified files carry this prominent notice. All changes
are **runtime overlays / sidecar components** — no upstream source file is
edited in the image itself:

| Component | What changed vs upstream |
|---|---|
| `branding-init` (our one-shot) | Replaces logo + favicon assets in `/var/www` at container start (brand assets; `img/logo.<hash>.svg` + `js/app.<hash>.js` wordmark bundle — asset names pinned to neko 2.9.0, re-pin on upgrade) |
| `title-proxy` (our proxy) | Rewrites HTML `<title>` to `Cloudbrowser: <email>` and injects the user identity badge; relays WebSocket |
| Sidecar services (ours) | `cdp-relay`, `downloads-api` + `janitor-loop`, `restart-api`, `window-manager`, `tooling-init`, tab-bar Chrome extension |
| Chrome launch | CfT 128 pin, kiosk flags, `--load-extension`, session restore |

### Attribution

The login page keeps the upstream link ("A self hosted virtual browser —
m1k1o/neko"). No neko trademark is used to imply endorsement.

## pyaes (legacy import)

- Location: `third_party/pyaes/`
- Upstream: https://github.com/ricmoo/pyaes
- Status: imported migration material; not used by the new runtime package.
- Upstream version/license: MIT; version 1.3.0 (as declared in the imported source).
- The upstream README and full license text should be added before production extraction.
