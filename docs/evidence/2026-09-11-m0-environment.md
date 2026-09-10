# M0 environment and baseline verification — 2026-09-11

## Scope

Confirm access, reproduce the prior source gates, establish the Mac-to-Linux
workflow, and compare deployed images. This record does not claim completion
of the final security review or complete M0 acceptance.

## Original Linux baseline

- Host: SSH alias `mother01` (reported hostname `srv636517`).
- Coolify project/environment: `pmo-city` / `development`.
- Container: `hermes-agent-gf68z1riv5f082shjcusvosw`; user `hermes`.
- Checkout: `/opt/data/pmo-city-cloudbrowser-work`.
- Source: `430a06603e8dff9531cc14042a01e38fff2b8874`, clean before verification.
- Python: 3.13.5; uv and the expected qualification Chromium executable available.
- `uv run make check`: **1006 passed, 7 skipped**, 146.44 seconds; all six
  validators passed. Four skips were missing Docker Compose CLI; three were
  the intentionally disabled production-form integration tests.

This reproduces the handoff result in the original environment. Unlike the
earlier native Mac run, the crypto and real-Chromium tests run here.

## Separate qualification workspace

An independent Git clone and Python environment were created at
`/opt/data/cloudbrowser-codex/repository` on the persistent `/opt/data` volume.
The volume had approximately 144 GB available at setup. The current container
also mounts persistent volumes at `/workspace` and `/home/hermes/.hermes`;
those locations were not used for the new checkout.

The Mac's documentation candidate `3eb071a8eb4a0914169e386b777ab99e2d2fdbc7`
was transferred as a verified Git bundle and checked out detached. No branch
was pushed to GitHub. A copy of the host's Compose v5.5.0 executable was added
only to `/opt/data/cloudbrowser-codex/bin` to enable fixture-only rendering tests.
Candidate verification:

- `uv run make check` with the test-tools PATH: **1010 passed, 3 skipped** in
  150.07 seconds; all six validators passed. All four Compose rendering checks
  now ran and passed. Only the intentionally disabled form tests skipped.
- `uv run make cloudfiles-boundary`: **80 passed** in 0.21 seconds.
- `uv run python -m compileall -q src tests`: passed.
- `git diff --check`: passed.
- Candidate remained at `3eb071a` with a clean working tree; original Hermes
  remained at `430a066` with a clean working tree.

The new Mac workspace's six validators and 17 documentation/layout/contract
checks also passed. Ten relative links in the workflow/README/evidence selection
were checked with no broken links. These results precede the documentation-only
commit recording this evidence; the tested runtime source is unchanged.

## Deployed-image comparison

All nine CloudBrowser application containers and ClamAV reported healthy.
For each application service, Docker's configured image digest exactly matched
the retained pin in `deploy/coolify/releases/v0.2.0-dev1/release-manifest.yaml`:
router, slot-supervisor, browser, viewer, agent-control, credential-broker,
cloudfiles, downloads, and identity-link.

The manifest attributes those pins to source
`50ce1984448ddf79621d4114f81c6a2b2b83d5fa`, qualification run `34402569940`.
Consequently the deployed image references are the prior release; they do not
qualify source `430a066` or the later documentation candidate. This check did
not independently revalidate image attestations or inspect possible container
filesystem changes. It establishes digest-reference agreement, not application
acceptance. No running service was restarted or redeployed.

## M0 remaining work

- Complete the post-remediation broker review against immutable source
  `430a066`, including replay/correlation, revocation races, unknown outcomes,
  exact targets, deadlines/SQLite waits, and secret directionality.
- Record each finding and disposition before a release-readiness decision.
- Carry profile/consent continuity and fresh-browser usability into M1/M2;
  a test baseline does not close those product acceptance gaps.
- Build and attest current-source images only after review; live qualification
  and deployment remain separate work.
