# TURN installation runbook

```yaml
id: CLOUDBROWSER-TURN
name: CloudBrowser coturn WebRTC relay
category: cloud-browser
scope: CloudBrowser project
status: design-only
owner: PMOC
dependencies:
  - CloudBrowser fleet and Neko viewer
  - tenant public IPv4 and provider firewall control
  - approved DNS record for the TURN hostname
  - approved credential and certificate boundary
compose: ./compose/compose.yaml.example
entrypoint: manual Coolify raw Docker Compose resource; Builder adapter not yet implemented
last_reviewed: 2026-08-31
```

## Purpose

Install coturn as a standalone Coolify Docker Compose resource for WebRTC relay
fallback. The consumer is CloudBrowser/n.eko when a VPN or restrictive client
network prevents direct ICE connectivity.

This is a CloudBrowser project procedure, not a production deployment approval.
The current CloudBrowser fleet is not changed by following this runbook.

## Prerequisites

- [ ] Tigo/technical owner approved the TURN deployment and public exposure.
- [ ] The CloudBrowser project, Coolify and the tenant edge are healthy.
- [ ] A public IPv4 and a provider firewall policy are available. A normal
      Cloudflare proxy or Cloudflare Tunnel is not sufficient for TURN.
- [ ] `turn.<tenant>.pmo.city` (or the approved tenant-neutral equivalent) is
      reserved as DNS-only and points to the TURN host.
- [ ] The selected coturn image tag has been reviewed and its digest is
      recorded before deployment. Do not use `latest` in production.
- [ ] A certificate and private key for the TURN FQDN are available through the
      approved secret/file boundary. Do not paste private key contents into Git.
- [ ] The credential issuer design is approved. A static username/password is
      acceptable only for an isolated lab, never for production.
- [ ] Provider transfer quota and the estimated concurrent relayed-viewer count
      are recorded.
- [ ] A rollback window and an operator with host-firewall access are assigned.

## Inputs

Copy [`variables.env.example`](./variables.env.example) and resolve every
`<tenant>`/`<value>` from the CloudBrowser deployment manifest. Keep secret
values out of Git, tickets and evidence.

Required values:

- tenant and TURN FQDN;
- public IPv4;
- coturn image tag and resolved digest;
- listener and relay port ranges;
- realm;
- credential mode and issuer secret reference;
- certificate/key references;
- provider firewall and host firewall change IDs;
- approved Coolify project/server/resource identifiers.

## Coolify Compose resource

1. Create a separate Coolify **Docker Compose** resource in the CloudBrowser
   project on the intended server. Do not add coturn to `cb-fleet-v2`.
2. Use [`compose.yaml.example`](./compose/compose.yaml.example) as the raw
   Compose source. The Compose file is the source of truth.
3. Define non-secret variables in the Compose/Coolify resource environment and
   mark required values with Coolify's `:?` syntax where appropriate.
4. Store secret values only in the Coolify encrypted environment/file mechanism
   or the approved Vaultwarden hand-off. Never put a TURN HMAC secret, private
   key or certificate body in this repository.
5. Do **not** configure a Coolify domain, Traefik router, HTTP proxy label or
   Cloudflare Tunnel for the coturn service.
6. Keep `network_mode: host` in the coturn service. Coturn's public listener,
   external address and relay range must map directly to the host network; a
   normal Coolify application network is not a substitute for public UDP
   routing. Confirm that this choice is permitted on the selected Coolify
   version/server before deployment.
7. Set the `TURN_PUBLIC_IP`, `TURN_REALM`, listener ports, relay range and
   certificate paths explicitly. Do not rely on automatic external-IP
   discovery in production.
8. Deploy only after the approval and firewall gates below are complete.

The template intentionally keeps no `ports:` mapping because host networking
binds coturn directly. This differs from ordinary Coolify application templates
that use `expose:` plus the Coolify HTTP proxy.

## Firewall and DNS order

Create the public exposure in this order:

1. Publish the DNS A record with proxying disabled:
   `turn.<tenant>.pmo.city → <TURN_PUBLIC_IP>`.
2. Allow UDP and TCP **3478** at the provider firewall and host firewall.
3. Allow TCP **443** for TURN-over-TLS fallback. Do not open UDP 443 unless a
   separately approved requirement exists.
4. Allow UDP **49160–49259** for coturn relay allocations.
5. Deny other coturn listener/relay ports and confirm no management port is
   exposed publicly.
6. Verify the DNS answer and certificate hostname from an external network.

For a different concurrency target, derive a narrower relay range and record the
reason. The range must be wide enough for the expected simultaneous allocations
and must be identical in coturn, provider firewall and host firewall.

## Deployment sequence

1. Take a Coolify/service recovery point and record the current resource state.
2. Confirm the Compose image tag and digest; replace any mutable `latest`.
3. Confirm the certificate and key are readable by the container at the exact
   paths configured in Compose, without printing their contents.
4. Confirm the coturn realm, public IPv4, listener port and relay range.
5. Deploy the Compose resource from Coolify.
6. Check container health and logs. Stop on any `external-ip`, certificate,
   realm, authentication or bind error.
7. Run [`verification.md`](./verification.md) from both an external network and
   the intended VPN network.
8. Do not connect CloudBrowser until the standalone relay passes the positive
   and negative TURN checks.
9. Connect a non-production Neko test instance with `NEKO_ICELITE=false` and
   `NEKO_ICESERVERS` containing TURN UDP, TURN TCP and TURN TLS URLs.
10. Verify that the VPN viewer selects a `relay` candidate and renders the
    desktop. Verify that the direct non-VPN path remains direct where possible.
11. Record the sanitized result in [`evidence-template.md`](./evidence-template.md).

## Credential integration

The coturn service expects the credential method selected in its Compose. For
production, use a time-limited REST credential derived from the shared secret.
The issuer must provide the Neko client configuration without exposing the shared
secret to the browser, end user or Git.

The CloudBrowser service currently has no documented, qualified per-owner TURN
credential injection path. Therefore:

- do not add a guessed environment variable to the live fleet;
- do not put a permanent TURN credential in `cb-fleet-v2`;
- implement and test the issuer/injection path as a separate reviewed change;
- bind any generated credential to the current slot owner if the product
  integration requires owner-specific issuance;
- test expiry, wrong-owner and failed-issuance behavior before claiming TURN
  integration is qualified.

## Operations

Monitor at minimum:

- coturn container health and restart count;
- allocation count and allocation failures;
- listener/relay port errors;
- ingress and egress bytes;
- CPU, memory and file-descriptor pressure;
- credential issuance failures and expiry behavior;
- direct-versus-relay ratio for CloudBrowser viewers.

Do not log HMAC secrets, generated passwords, private keys, browser cookies,
SDP, client IPs beyond the approved retention policy or media contents.

## Stop/rollback triggers

Stop or roll back if:

- a listener or relay range is exposed beyond the approved firewall policy;
- the certificate hostname or TLS chain is wrong;
- a credential is accepted after expiry or by the wrong tenant/owner;
- allocations succeed but relay packets do not pass;
- direct non-VPN CloudBrowser behavior regresses;
- the relay cannot be disabled without restoring the previous CloudBrowser path.

Use [`rollback.md`](./rollback.md). Do not delete the Coolify resource or its
secrets until evidence and the change record are preserved.
