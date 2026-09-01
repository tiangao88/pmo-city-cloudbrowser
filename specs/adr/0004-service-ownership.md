# ADR-0004: Explicit service ownership

- Status: Accepted as repository bootstrap policy
- Date: 2026-09-01

The repository contains separately deployable service boundaries even when a
Coolify installation runs them as one Compose bundle. Router, slot supervisor,
viewer, downloads, and Credential Broker have explicit ownership and API
contracts. They must not silently share privileged filesystem access or
credential capabilities.
