# CloudBrowser Credential Broker API v1

The agent submits a profile-bound login intent and receives only a bounded
status result: `authenticated`, `mfa_required`, `failed`, `not_shared`, or
`unsupported`, plus a non-sensitive error code, request ID, and duration.

The detailed schema is part of proposal v0.2 and must be frozen before the
first implementation release.
