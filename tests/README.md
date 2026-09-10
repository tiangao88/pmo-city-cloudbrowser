# Test suites

## Environment and evidence

Use Python 3.12+ with `uv`. The current vault crypto loader requires Linux
OpenSSL library names (`libcrypto.so.3` or `libcrypto.so`); native macOS runs
do not reproduce the Linux crypto/custody qualification without a portability
change. Use the supported Linux runtime for the full qualification, with real
Chromium and Docker Compose available. Record all skips and their reasons.

The Basic real-browser tests honor `CB_TEST_CHROME_EXECUTABLE`. The current
Authentik real-browser fixture instead hard-codes
`/opt/data/browsers/chromium-1228/chrome-linux64/chrome`; making that fixture
portable/configurable remains M0 work. A browser installed elsewhere does not
make those tests run.

On macOS, the special-file fixture may exceed the Unix socket path limit under
the default pytest temporary root. A short, newly allocated `--basetemp`
directory resolves that fixture constraint; never point it at valuable existing
data because pytest clears its base directory.

`make check` runs validators and the full suite. `make cloudfiles-boundary`
runs the focused public file boundary checks. A green run establishes only the
tested environment and source; image provenance and deployed user journeys
require their own evidence. See
[implementation status](../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md).

## Layout

- `unit/` — isolated domain behavior;
- `contract/` — API/schema compatibility;
- `integration/` — service boundaries and persistence;
- `security/` — adversarial zero-exposure and owner-binding tests;
- `installation/` — Compose, manifest, volume, and side-by-side isolation;
- `e2e/` — controlled development-stack journeys;
- `live/` — explicitly opt-in qualification instructions only; no credentials
  or production artifacts belong in the repository.
