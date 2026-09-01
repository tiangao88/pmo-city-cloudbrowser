# TURN upgrade

An upgrade is a reviewed coturn image or configuration change, not an automatic
mutable-tag pull. The initial template uses `coturn/coturn:4.17.2-r0` as a
reviewed starting tag; production must record the resolved digest.

## Before the change

- [ ] Read the coturn release notes and image changelog.
- [ ] Review changes to TLS, authentication, listener and relay behavior.
- [ ] Test the candidate image with the exact Compose and a disposable relay
      allocation.
- [ ] Confirm the public IP, DNS, certificate, relay range and firewall policy.
- [ ] Confirm the provider transfer budget and maintenance window.
- [ ] Capture current sanitized health, listener and allocation evidence.
- [ ] Confirm the CloudBrowser/Neko integration rollback point.

## Execution

1. Keep the same TURN FQDN, public IP, realm, certificate and relay range.
2. Update only the reviewed image tag/digest or explicitly reviewed settings.
3. Deploy through Coolify; do not edit generated runtime containers directly.
4. Check coturn logs and the process/listener contract.
5. Run [`verification.md`](./verification.md), including VPN, non-VPN, negative
   credential and restart checks.
6. Record the new image digest and sanitized evidence.

## Failure

Stop on authentication, TLS, bind, external-IP, allocation or bandwidth
regressions. Use [`rollback.md`](./rollback.md). Do not weaken authentication or
open a wider relay range as an upgrade workaround.
