# W3-5 — Isolated agent-browser companion PoC

Date: 2026-08-31
Status: **COMPLETE — isolated local PoC PASS; no production adoption or live
CloudBrowser fleet mutation performed.**

## 1. Scope and isolation boundary

The PoC evaluated `agent-browser` as a deterministic hands/verifier around the
existing browser-use baseline. It ran against the already-running dedicated
headless Chrome on CDP port `9333`, not either CloudBrowser fleet slot. The
PoC used named agent-browser sessions with `--pin-tab`; no CloudBrowser
credentials, cookies, OTPs, business data, or live fleet state were accessed.
The only navigation targets were public `example.com`/IANA pages and a local
`data:` test page.

This is a tooling qualification, not a deployment approval. W3-1 remains the
authenticated-surface gate and W3-6 remains the rollout/service-browser gate.
There was no live fleet change and no credentials were used.

## 2. Versions and baseline

- `0.35.2` (the executed `agent-browser 0.35.2` CLI), npm package, Apache-2.0.
- Package metadata: Node `v26.5.1`, npm `11.17.0`; package engine requires Node
  `>=24.0.0` and pnpm `>=11.0.0`.
- npm registry integrity: `sha512-1JvgqC1NZrCTcIsdPB5T51XgVtF70WEgH46XszhRJdCBwuab0jV4mySLgtoNKvlb/X8PR5dce/8Regd0aUANZA==`.
- Dedicated Chrome endpoint: Chrome version `151.0.7922.34`, CDP `9333`; the
  CDP `/json/version` probe returned `Chrome/151.0.7922.34`.
- Existing Hermes browser-use baseline: the browser-use/browser-harness path
  drove the same public `example.com` page successfully through the existing
  Browser Use CLI session; the harness reported version `0.1.9`.
- Installation was isolated under `/opt/data/w3-5-poc`; nothing was added to
  the repository or the Hermes runtime environment.

## 3. Executed comparison

### 3.1 Baseline browser-use result — PASS

The existing browser-use harness opened `https://example.com/`, waited for
load, and returned the page URL/title plus body text. The result was:

- URL: `https://example.com/`
- Title: `🐴 Example Domain`
- Body text contained `Example Domain`, the documentation disclaimer, and
  `Learn more`.

### 3.2 agent-browser attach and deterministic control — PASS

The CLI attached with `connect 9333`, opened the same public page, and returned
an accessibility snapshot with stable refs:

```text
- heading "Example Domain" [level=1, ref=e1]
- link "Learn more" [ref=e2]
```

The PoC then verified:

- `open`, `get url`, and `get title`;
- `snapshot` and `read`;
- `click @e2` navigation;
- CSS-selector interaction on a local data page (`click #b`);
- `fill #name "PoC user"` followed by a value readback;
- JavaScript evaluation to add a marker;
- JSON output for snapshot, request log, accessibility audit, and tab list.

### 3.3 Multi-tab and tab-loss behavior — PASS with explicit recovery

The CLI created stable tab IDs (`t1`, `t2`, `t3`), assigned labels (`iana`,
`example`), switched by ID and label, and returned the expected URL for each
selected tab. With `--pin-tab`, closing the bound tab did not silently select a
wrong user tab in the tested session; the remaining tab became the active
browser target and a new tab could be explicitly created for recovery.

This is useful but does not replace CloudBrowser owner binding. Production use
would still need the router's owner/readiness barrier and an explicit
slot-reassignment recovery policy.

## 4. Evidence and QA capabilities — PASS

The PoC exercised or verified the following agent-browser capabilities:

- **Snapshot diff:** baseline-file comparison returned a structured diff and
  additions/removals after page mutation.
- **Screenshot diff:** baseline comparison returned `match: true`,
  `differentPixels: 0`, and `mismatchPercentage: 0.0` for the unchanged page.
- **Accessibility:** `a11y --json` ran vendored axe-core `4.12.1` and returned
  structured counts/violations. The intentionally minimal local HTML page
  produced expected WCAG violations; this confirms the audit path, not page
  conformance.
- **Recording:** `record start/stop` produced a WebM artifact of `167423`
  bytes.
- **Chrome trace:** `trace start/stop` produced a JSON trace artifact of
  `14187084` bytes.
- **Network request log:** `network requests` returned captured request
  metadata for the public page.
- **HAR:** `network har start/stop` produced a `266405`-byte HAR. HAR content
  can contain authentication headers and response bodies and must be treated
  as sensitive; it was not committed or shared.
- **Compact operation:** snapshots and JSON responses are directly consumable
  by an agent without requiring an LLM inside the browser tool.

## 5. Reliability and cost/token assessment

This bounded PoC did not claim a statistically meaningful success rate or
measure token billing. It established the qualitative control-loop difference:

- browser-use baseline: successful public-page read through the existing
  autonomous harness;
- agent-browser: successful CDP attach, deterministic snapshot/ref actions,
  tab selection, structured diffs, audit, request capture, recording, and
  trace on the same dedicated Chrome;
- agent-browser itself adds no model call to the hands path, so its direct
  orchestration-token cost in this PoC was zero. It still has execution and
  artifact-storage costs, and a fair end-to-end token comparison requires a
  fixed task corpus and the same model/controller, which was outside this
  isolated pass.

The reliability result is therefore **functional PASS, not a production SLO
claim**. A future W3-5 extension could run repeated fixed tasks to obtain
step-success, recovery, latency, and artifact-size distributions.

## 6. Owner binding and deterministic rescue assessment

- CDP attach and `--pin-tab` were verified on a dedicated Chrome only.
- `--pin-tab` prevents silent fallback when the bound tab is gone according to
  the CLI contract; the tested multi-tab run also demonstrated explicit tab
  recovery.
- No agent-browser feature tested here identifies the CloudBrowser slot owner
  or authorizes a cross-slot operation.
- Therefore rescue remains **compatible only when wrapped by existing
  CloudBrowser controls**: resolve the requested owner, verify slot readiness,
  use the existing router/restart API, and reject `owner_mismatch`. The PoC
  did not weaken or bypass those controls.

## 7. Recommendation

**RECOMMENDATION: ADOPT agent-browser as a companion deterministic instrument
around browser-use, not as a replacement for browser-use's autonomous engine.**

Adopt first in a non-production integration branch or service-side verifier for
snapshot/ref actions, structured evidence, and deterministic checks. Keep the
current browser-use driver as the W2-compatible autonomous brain until a fixed
corpus demonstrates equivalent or better end-to-end task completion.

Do not add agent-browser to live CloudBrowser slots from this PoC alone. Before
production adoption, complete an owner-aware adapter test, define HAR/recording
redaction and retention rules, pin the package/runtime supply chain, and run a
repeated cost/reliability corpus. This recommendation satisfies W3-5's
keep/reject decision without closing W3-1 or authorizing W3-6 rollout.

## 8. Reproducibility artifacts

Local-only artifacts were written below `/opt/data/w3-5-poc` and intentionally
excluded from git:

- `before.snapshot.txt`, `after.snapshot.txt`, `snapshot.json`;
- `before.png`, `after.png`, `w35-baseline.png`;
- `session.webm`, `session.trace.json`, `session.har`;
- `requests.json`, `a11y.json`, `tabs.json`;
- npm-installed package under `node_modules/`.

The artifacts contain public-page data only in this run, but HARs, screenshots,
and recordings are classified as potentially sensitive by policy and must be
redacted/reviewed before external sharing.
