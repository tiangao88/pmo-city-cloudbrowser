# Legacy import map

The following material was imported from
`pmo-city-builds/internal/luna/tools-considered/cloud-browser-service`.

- `specs/archive/pmo-city-builds-w2-w3/` preserves the specification and
  qualification history.
- `legacy/scripts/` preserves runtime scripts, supervisor configs, tests,
  probes, and deployment helpers as migration input.
- `integrations/hermes/pmoc-cdp-cloudbrowser/` preserves the PMO City CDP
  integration reference without importing the vendored browser harness.

This mapping is deliberately explicit. Legacy code is not the refactored
service implementation and must not be deployed as the new product without
new contracts and security tests.
