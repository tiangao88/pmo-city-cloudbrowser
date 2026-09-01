# TURN rollback

## Preconditions

- [ ] The failure, time and affected network path are recorded without SDP,
      credentials or client media.
- [ ] A known-good coturn image/digest and Compose revision are available.
- [ ] The CloudBrowser/Neko pre-TURN configuration is preserved.
- [ ] The operator can change Coolify and the provider/host firewall.

## Procedure

1. If the relay is unsafe or misconfigured, remove its public listener in the
   provider/host firewall first; preserve sanitized logs and counters.
2. Stop or redeploy the TURN Coolify resource with the known-good image and
   exact prior configuration.
3. Run the readiness and negative credential checks.
4. If the CloudBrowser integration changed, restore the previous Neko/router
   configuration through its own reviewed deployment path. Do not edit a live
   container manually as the final state.
5. Verify a non-VPN direct CloudBrowser session and a controlled VPN failure or
   known-good fallback, without mutating owner, queue, cookie or SSO state.
6. Reopen only the approved firewall ports after the relay passes verification.
7. Record the rollback result and open a finding for the failed version/change.

## Decommission

After approval, remove DNS, firewall allowances, the Coolify resource and only
then its secret/certificate references. Preserve the change record, image
fingerprint and sanitized evidence according to the tenant retention policy.
