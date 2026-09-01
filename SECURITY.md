# Security Policy

## Scope

Report vulnerabilities in CloudBrowser, its installation manifests, browser
control surface, credential-broker boundary, or release process privately.
Do not open an issue containing credentials, browser-profile data, private
URLs, cookies, tokens, OTP material, HAR files, screenshots with sensitive
content, or exploit details.

## Non-negotiable invariants

1. The agent receives intent results, never credential material.
2. Only the Credential Broker may consume the credential-fetch capability.
3. Browser control is owner-, profile-, slot-, tab-, origin-, and nonce-bound.
4. Cookie/storage reads, network bodies/auth headers, password values,
   unrestricted Runtime.evaluate, raw CDP, filesystem, and process access are
   denied or mediated for the agent.
5. Secrets never enter logs, audit events, traces, screenshots, or artifacts.
6. Revocation and stale-owner checks fail closed.
7. Different installations never share persistent browser or broker state.

## Development rule

Security-sensitive changes require a failing security test before production
code changes. Never test against live customer credentials or production
browser profiles. The imported `legacy/` tree is migration input and must not
be treated as permission to copy its old credential-handling boundary into the
new services.
