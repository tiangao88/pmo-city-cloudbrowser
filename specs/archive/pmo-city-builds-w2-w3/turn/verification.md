# TURN verification

Run the checks after installation, after any firewall/DNS/certificate change,
and after every coturn or Neko upgrade. Record only sanitized outcomes.

## Readiness and exposure

- [ ] Coolify shows the dedicated TURN Compose resource healthy.
- [ ] The running coturn image tag and immutable digest are recorded.
- [ ] The container uses host networking only where explicitly approved.
- [ ] The coturn process is listening on TCP/UDP 3478 and TCP 443 as intended.
- [ ] UDP relay ports exactly match `TURN_MIN_PORT`–`TURN_MAX_PORT`.
- [ ] No HTTP domain, Traefik router, Cloudflare proxy or Tunnel is attached.
- [ ] No Docker socket, host root, unrelated tenant volume or writable secret
      mount is present.
- [ ] The certificate SAN covers the TURN FQDN and the key is not world-readable.
- [ ] Logs contain no bind, realm, external-IP, certificate or authentication
      errors.
- [ ] DNS resolves the TURN hostname to the intended public IPv4 from an
      external resolver.

## Positive network path

Run from a network outside the VPS and from the intended VPN. A TCP connect is
only a listener check; it is not proof that TURN can allocate a relay.

- [ ] TCP 3478 is reachable where enabled.
- [ ] UDP 3478 reaches the listener.
- [ ] TCP 443 reaches the TURN TLS listener and presents the expected certificate.
- [ ] A valid short-lived credential completes a TURN allocation.
- [ ] A WebRTC test using the TURN server selects a `relay` candidate.
- [ ] The relay port observed is inside the declared range.
- [ ] A VPN CloudBrowser test renders the desktop rather than only the outer
      loading shell.
- [ ] CloudBrowser WebRTC diagnostics show the expected relay candidate and no
      owner/queue/authentication mutation.
- [ ] A non-VPN CloudBrowser test remains direct where the network permits it.

## Negative and abuse paths

- [ ] Missing credentials are rejected.
- [ ] Malformed credentials are rejected.
- [ ] Expired credentials are rejected after the approved TTL.
- [ ] A credential for an unapproved identity cannot be used if the integration
      requires owner binding.
- [ ] Unallocated relay ports are not reachable as a general-purpose proxy.
- [ ] Multicast/loopback peer restrictions are active.
- [ ] Unlisted public ports and management/CLI endpoints are closed.
- [ ] Stopping coturn does not corrupt CloudBrowser router state, owner binding,
      cookies or queue state; the VPN path fails visibly and can be rolled back.

## Resource and monitoring checks

- [ ] CPU, memory, process count and file descriptors stay within the resource
      contract during a representative relayed session.
- [ ] Ingress and egress byte counters are captured without logging media or
      credentials.
- [ ] Allocation count and failed allocations are observable.
- [ ] Provider transfer quota and certificate expiry alerts are configured.
- [ ] A restart leaves the service healthy and does not require a data restore.

## Evidence

Record in [`evidence-template.md`](./evidence-template.md):

- UTC test time, tenant/resource identifier and image digest;
- source network class (`external`, `VPN`, `non-VPN`), not private user data;
- listener and relay-port result;
- selected ICE candidate type (`relay`/`srflx`/`host`), never SDP or credentials;
- sanitized allocation/throughput result;
- positive, negative and rollback outcomes;
- firewall/DNS/certificate change references;
- operator, approver and open exceptions.
