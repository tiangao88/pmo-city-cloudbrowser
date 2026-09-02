# Credential Broker service

The Credential Broker owns deterministic, status-only login execution.

## Current slice (step 13)

This repository now contains the generic, dependency-injected broker boundary:

- server-bound intent validation and status-only results;
- deterministic coordinator with a second binding check after credential fetch
  and immediately before adapter execution;
- exact-origin form, HTTP Basic, SSO, and RFC 6238 TOTP adapter contracts;
- one-shot, TTL-bound human MFA handoff without code retention;
- bounded idempotency and `cloudbrowser.audit.v1` metadata events with
  credential-shaped payload rejection;
- synthetic contract/security coverage only.

The broker never returns passwords, tokens, cookies, storage values, page
content, network bodies, raw exceptions, OTP seeds, or one-time codes.

## Deliberate non-goals

No live Vaultwarden/GrantHub access, Authentik/TinyAuth daemon, network-hook
capture, router-side unwrap, or real user login is included in this slice.
The production grant/session provider and browser capability must be injected
behind these contracts and separately qualified before the service can become
an installable live credential broker. The release remains `installable: false`.
