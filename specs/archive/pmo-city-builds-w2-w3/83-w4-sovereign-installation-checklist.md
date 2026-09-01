# W4 — Sovereign single-tenant installation checklist

Date: 2026-08-31
Status: **CHECKLIST READY — not a deployment approval.**
Scope: one PMO City tenant with its own CloudBrowser fleet, state, secrets,
network exposure, operators, and retention decision.

This checklist is a preparation artifact for W4. It does not authorize a
Coolify deployment, DNS change, firewall change, credential rotation, service
restart, or production data operation. Obtain the tenant owner's explicit
approval at the deployment gate.

## 1. Tenant and ownership boundary

- [ ] Confirm a tenant-specific deployment and data-residency decision.
- [ ] Confirm the deployment is a new sovereign single-tenant brick, not a
      shared fleet or shared user-profile volume. The isolation boundary must
      be verified explicitly before release.
- [ ] Allocate separate Coolify project/resource identifiers and a documented
      rollback target.
- [ ] Define personal-browser and service-browser ownership separately; a CRM
      or other service browser must not be presented as a person's browser.
- [ ] Confirm all pilot/business users have canonical identities and the
      intended access group; reject aliases and unvalidated identity strings.

## 2. Repository and image provenance

- [ ] Pin the exact repository commit and every container image tag/digest;
      never use `latest` for the installation.
- [ ] Review the staged diff and run focused plus regression tests before the
      release is eligible for deployment.
- [ ] Confirm no secrets, tokens, cookies, OTPs, passwords, private keys, or
      business-data exports are present in Git, image layers, test fixtures, or
      build logs.
- [ ] Record the source revision, image digests, configuration revision, and
      verification operator in the tenant release record.

## 3. Secret and identity boundary

- [ ] Provision secrets only through the approved secret boundary; do not paste
      values into Git, tickets, chat, browser URLs, or model context.
- [ ] Use per-slot broker credentials and server-derived owner binding; do not
      reintroduce a shared user credential or shared grant store.
- [ ] Verify the SSO/Authentik issuer, client, redirect, group policy, and
      broker vault-item selection with a non-production test identity.
- [ ] Verify spec-56 identity-cookie stripping remains enabled: no identity
      cookie is copied between users or restored from an archive.
- [ ] Define rotation, revocation, emergency disablement, and post-rotation
      read-back procedures for every infrastructure credential.

## 4. Network and surface exposure

- [ ] Reserve the approved tenant DNS names and validate certificates/SANs.
- [ ] Put the viewer and CloudFiles behind the intended SSO gateway; confirm
      raw unauthenticated HTTP is not exposed.
- [ ] Keep CDP, restart APIs, broker APIs, router control endpoints, state
      volumes, and supervisor controls internal-only.
- [ ] Review firewall, reverse-proxy, WebSocket, WebRTC, and optional TURN
      exposure separately; TURN is not an HTTP route.
- [ ] Confirm logs and health endpoints do not disclose query-string passwords,
      authorization headers, cookies, grant material, or arbitrary page data.

## 5. Data, storage, and retention

- [ ] Allocate distinct per-user archive/profile/download areas and verify
      filesystem ownership, permissions, quota, and backup/restore boundaries.
- [ ] Confirm user downloads use the approved 5 GB quota and 90-day retention;
      verify ClamAV ingest/quarantine behavior before accepting files.
- [ ] Approve a tenant-specific 90-day minimum audit-retention decision, access
      role, export/hold process, and GDPR erasure procedure.
- [ ] Configure append-only or immutable audit storage where available; test
      synthetic expiry and legal-hold behavior before destructive cleanup.
- [ ] Verify deletion removes the user's profile/archive/downloads and required
      identifying audit records, with only a secret-free completion event.

## 6. Health and recovery qualification

- [ ] Confirm Coolify reports the intended resource and all applications
      healthy; record read-back evidence.
- [ ] Verify router `/health`, sanitized `/fleet/status`, each slot `/health`,
      and the owner-bound readiness barrier.
- [ ] Test fresh assignment, queue waiting/offered/backed-off states, active
      reload, idle suspend/wake, Chrome/CDP restart, and viewer rescue.
- [ ] Test owner switch: Chrome and title-proxy stop before profile restore;
      no foreign tabs, History rows, cookies, archives, or grants appear.
- [ ] Test container/service recreate with a durable sessions mount and an
      owner-bound boot hint; distinguish infrastructure health from
      authenticated-surface proof.
- [ ] Test malformed live snapshot, last-good fallback, valid empty workspace,
      owner mismatch, and archive marker failure.
- [ ] Define alert thresholds, on-call ownership, evidence sanitization, and
      escalation for viewer/Vulkan/title-proxy, broker, queue, and storage
      failures.

## 7. Release and rollback gate

- [ ] Obtain explicit tenant-owner approval for the exact resource, commit,
      image digests, configuration, data migration, and maintenance window.
- [ ] Take and verify a rollback-safe backup of tenant configuration and
      per-user state according to the approved policy; never copy secrets into
      an unapproved location.
- [ ] Deploy only the approved tenant resource; do not mutate another tenant or
      the shared dev fleet as a side effect.
- [ ] Read back service health, owner binding, queue identity, visible identity,
      audit emission, and retention configuration after deployment.
- [ ] If any acceptance item is `not_proven`, stop rollout and use the recorded
      rollback path. Do not declare success from a green outer health check.
- [ ] Record final verdict, source/image/config revisions, sanitized evidence,
      outstanding risks, and next review date.

## 8. W4 handoff outputs

- [ ] Tenant installation record and explicit approval reference.
- [ ] Immutable source/image/config manifest.
- [ ] Secret-manager references without secret values.
- [ ] Network and data-flow diagram with per-user boundaries.
- [ ] Health, recovery, alert, escalation, and rollback runbooks.
- [ ] Retention, legal-hold, and erasure decision record.
- [ ] Verification report with no credentials, cookies, OTPs, passwords, or
      business data.
