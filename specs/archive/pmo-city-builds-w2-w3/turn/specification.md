# TURN specification

## 1. Purpose and scope

A TURN server is a selective WebRTC relay. It is used when a browser cannot
form a working direct ICE path to the CloudBrowser/n.eko media endpoint, for
example because the browser is behind a VPN, symmetric NAT or a restrictive
firewall.

```text
CloudBrowser/n.eko ── direct ICE when possible ── client browser
         │                         │
         └──── TURN relay fallback ┘
```

TURN does not carry CloudBrowser HTTP, CDP, authentication cookies or browser
application traffic. It relays WebRTC media and data channels only. It does not
fix a broken router, title-proxy, Neko WebSocket, Chrome or SSO-broker path.

Initial scope:

- tenant-local Coolify deployment;
- coturn official container image;
- IPv4 first, with IPv6 explicitly disabled until tested;
- CloudBrowser/n.eko integration through `NEKO_ICESERVERS`;
- UDP relay as the primary path, TCP/TLS fallback on port 443 for restrictive
  VPNs;
- no public web UI and no Coolify HTTP domain route.

## 2. Deployment boundary

The TURN relay must be an independent Coolify Compose resource from the
CloudBrowser fleet. It must not be put behind the Coolify/Traefik HTTP proxy:
TURN is not HTTP, and the relay requires public UDP ports plus TCP/TLS fallback.

Recommended topology:

```text
public DNS: turn.<tenant>.pmo.city → VPS public IPv4
                                      │
                         provider firewall / host firewall
                         UDP/TCP 3478, TCP/TLS 443
                         UDP relay range 49160–49259
                                      │
                              Coolify Compose
                                      │
                                  coturn
```

The public TURN hostname is DNS-only at any DNS provider used for the tenant.
Do not proxy TURN through Cloudflare's normal HTTP proxy or a Cloudflare Tunnel.
If the provider cannot expose the required UDP range, use a separate small VPS
with a public IPv4 address.

## 3. Required runtime contract

| Area | Required contract |
| --- | --- |
| Image | `coturn/coturn:4.17.2-r0` initially; replace only after review and digest capture |
| Service | One service named `turn` |
| Ports | UDP/TCP 3478; TCP 443; UDP 49160–49259 relay range |
| Addressing | `TURN_PUBLIC_IP` is the VPS public IPv4; `TURN_REALM` is the tenant TURN FQDN |
- Auth | `use-auth-secret` / REST-style time-limited credentials; never a permanent public user. The Compose intentionally omits the redundant `lt-cred-mech` flag because coturn warns when it is combined with `use-auth-secret`. |
| TLS | Certificate and private key mounted from the approved secret/file boundary; required for `turns:` on 443 |
| Logging | stdout only; no request payloads or credentials in the evidence record |
| Persistence | No application data; an optional small `turn-data` volume is for runtime state only |
| Exposure | No Coolify HTTP domain, no Traefik labels, no host management endpoint |
| Resource target | 1 vCPU and 512 MB–1 GB RAM for the two-slot pilot; raise after measured load |
| Capacity target | At least 100 Mbps usable public network for the two-slot pilot |
| Relay ports | Start with 100 UDP ports; size from concurrent allocations and provider limits |
| IPv6 | Disabled in the first deployment unless the VPS, firewall and client path are tested together |

The relay range is intentionally separate from Neko's current EPR range
(`52101–52200`). Neko's EPR ports are the media endpoint ports used when the
browser connects directly to a slot. TURN allocations use the coturn relay
range. Do not assume that opening one range makes the other range reachable.

## 4. CloudBrowser/n.eko integration

Neko v2 uses the JSON environment variable `NEKO_ICESERVERS`. A client-facing
configuration should contain the TURN server before any optional STUN server,
with both UDP and TLS/TCP URLs:

```json
[
  {
    "urls": [
      "turn:turn.<tenant>.pmo.city:3478?transport=udp",
      "turn:turn.<tenant>.pmo.city:3478?transport=tcp",
      "turns:turn.<tenant>.pmo.city:443?transport=tcp"
    ],
    "username": "<short-lived-username>",
    "credential": "<short-lived-credential>"
  },
  {
    "urls": ["stun:stun.<approved-provider>:<port>"]
  }
]
```

The placeholder credential must be replaced by an integration that issues
short-lived TURN REST credentials from the shared secret. Do not put a
long-lived coturn secret or permanent username/password in the Neko Compose.
For coturn `use-auth-secret`, the username is normally an expiry timestamp plus
an identity, and the credential is the base64 HMAC-SHA1 result for that
username. The exact issuing component and TTL must be reviewed before enabling
production relay use.

The current CloudBrowser fleet has `NEKO_ICELITE=false`, which is required for
Neko's TURN integration. Keep it false for this design. If Neko's configuration
or version changes, re-check the upstream ICE/TURN behavior before rollout.

**Important integration gap:** this package does not claim that the current
CloudBrowser router/broker can yet issue per-owner TURN credentials or safely
inject `NEKO_ICESERVERS` into the live fleet. That is a separate implementation
change. The relay can be installed and tested in isolation first.

## 5. Capacity model

The current fleet setting is `NEKO_VIDEO_BITRATE=2048` kbps. A TURN relay
carries traffic in both directions at the server boundary, so a conservative
planning formula is:

```text
TURN Mbps ≈ viewers × video_mbps × 2 × 1.15–1.25
TURN GB/hour ≈ viewers × video_mbps × 2 × 3600 / 8 / 1000 × 1.15–1.25
```

For the current 2.048 Mbps stream:

| Concurrent relayed viewers | Planning throughput | Approx. traffic/hour |
| ---: | ---: | ---: |
| 1 | 4.7–5.1 Mbps | 2.1–2.3 GB |
| 2 | 9.4–10.2 Mbps | 4.2–4.6 GB |
| 5 | 23.6–25.6 Mbps | 10.6–11.5 GB |
| 10 | 47.1–51.2 Mbps | 21.2–23.0 GB |

These are planning values, not billing guarantees. Measure actual ingress and
egress, including audio, data channel, retransmission and connection churn.
Bandwidth is the primary cost; coturn's CPU/RAM demand for this pilot is small.
Do not promise a monthly transfer budget until the provider's billing model and
actual relayed-session ratio are known.

## 6. Security requirements

- Use `use-auth-secret` and a short credential TTL; never enable an anonymous
  or permanent shared relay account.
- Set a specific `realm` and `fingerprint`; disable multicast peers.
- Bind the listener and relay to the intended public IPv4. Do not use automatic
  external-IP discovery without recording the resulting address.
- Use a certificate whose hostname is the TURN FQDN. Keep the private key out of
  Git and out of ordinary Compose environment output.
- Allow relay traffic only on the declared port range. Keep the range as small
  as the measured concurrency requires, then expand deliberately.
- Do not expose coturn's CLI, admin interface or a Coolify public HTTP route.
- Do not log TURN credentials, HMAC secrets, cookies, OTPs or client content.
- Rate-limit or monitor allocation abuse at the provider edge where available.
- Treat the public IP as infrastructure metadata and record it only in the
  tenant deployment manifest/evidence, not in this reusable template.

## 7. Acceptance boundary

TURN is not accepted for CloudBrowser until all of these are true:

- the service is healthy and the running image digest is recorded;
- DNS resolves the TURN hostname to the intended public IPv4;
- provider and host firewalls allow only the declared TURN/listener/relay ports;
- coturn starts with no certificate, realm, auth or address errors;
- a time-limited credential can allocate and relay traffic;
- an expired or malformed credential is rejected;
- a VPN client can load the CloudBrowser desktop, not only the outer shell;
- browser WebRTC diagnostics show a `relay` candidate selected;
- a non-VPN direct path still works and does not unnecessarily select TURN;
- stopping TURN causes the VPN test to fail closed/visible rather than silently
  corrupting owner, authentication or queue state;
- all observed public exposure and rollback evidence is recorded.

## 8. Non-goals and open decisions

- This document does not authorize production deployment.
- It does not select a TURN hosting provider or monthly transfer plan.
- It does not modify the live `cb-fleet-v2` Compose or Coolify service.
- It does not implement the credential issuer or Neko configuration change.
- It does not assert that Cloudflare Tunnel can carry the WebRTC relay path.
- It does not make the current W3-1 authenticated-surface gate pass.

Open decisions before implementation:

1. choose a public IPv4 host and provider transfer allowance;
2. decide whether TURN is tenant-local or a separately isolated PMO City service;
3. define the credential issuer, owner binding and TTL;
4. obtain/issue the TURN certificate and DNS record;
5. test Neko's exact current build with `NEKO_ICESERVERS` and `NEKO_ICELITE=false`;
6. approve the public firewall change and a rollback window.
