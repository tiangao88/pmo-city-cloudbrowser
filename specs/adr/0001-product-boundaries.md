# ADR-0001: Separate CloudBrowser and Credential Broker boundaries

- Status: Accepted as repository bootstrap policy
- Date: 2026-09-01

CloudBrowser owns persistent owner-bound browsers, lifecycle, routing, viewer,
restricted control, and downloads. The Credential Broker owns deterministic
credential acquisition, adapter execution, verification, and redacted audit.
Hermes may issue intent but must not receive credential material. Authentik is
an adapter, not the generic broker definition.

The legacy code is imported under `legacy/` until a test-first extraction is
complete. New CloudFiles implementation must not import or copy the legacy
`downloads-api.py` or monolithic router/storage process.
