# TURN evidence — YYYY-MM-DD

**Runbook ID:** `RB-PLATFORM-TURN`
**Tenant:** `<tenant>`
**Coolify resource:** `<resource identifier>`
**Image/digest:** `<coturn tag and digest>`
**TURN FQDN:** `<hostname>`
**Public IP:** `<record in restricted deployment evidence>`
**Result:** `pass | partial | fail`

| Check | Expected | Observed | Result |
| --- | --- | --- | --- |
| Coolify service | Healthy dedicated Compose resource |  |  |
| Listener | Approved TCP/UDP listener ports only |  |  |
| TLS | FQDN certificate valid on TLS listener |  |  |
| Relay range | Declared UDP range only |  |  |
| DNS/firewall | Intended public IP and approved ports |  |  |
| Valid credential | Allocation and relay succeed |  |  |
| Expired credential | Rejected |  |  |
| VPN WebRTC | `relay` candidate and desktop renders |  |  |
| Non-VPN WebRTC | Direct path preferred where possible |  |  |
| CloudBrowser safety | Owner/queue/cookie/SSO state unchanged |  |  |
| Resource use | CPU/RAM/fd/traffic within plan |  |  |
| Restart | Service recovers without data restore |  |  |
| Rollback | Previous path restored or failure isolated |  |  |

## References

- Provider firewall change: `<change ID>`
- Host firewall change: `<change ID>`
- DNS change: `<change ID>`
- Certificate reference/expiry: `<secret reference / date>`
- Credential issuer reference/TTL: `<component / duration>`
- Approval record: `<change ID>`

Record only candidate type, sanitized counters and pass/fail outcomes. Never
include TURN credentials, HMAC secrets, certificates, private keys, SDP,
cookies, OTPs, screenshots containing secrets or client media.
