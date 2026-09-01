# TURN sources

| Source | Type | Retrieved | Used for |
| --- | --- | --- | --- |
| [coturn Docker image README](https://github.com/coturn/coturn/blob/master/docker/coturn/README.md) | Upstream image/configuration | 2026-08-31 | Official image tags, host networking, listener and relay-port examples |
| [coturn project](https://github.com/coturn/coturn) | Upstream implementation | 2026-08-31 | Supported image/release references |
| [n.eko v2 getting started](https://github.com/m1k1o/neko/blob/v2.9.0/docs/getting-started/README.md) | Upstream CloudBrowser/WebRTC guidance | 2026-08-31 | `NEKO_ICESERVERS`, coturn integration, ICE-lite/TURN caveat and UDP ports |
| [n.eko v2 configuration](https://neko.m1k1o.net/docs/v2/configuration) | Upstream configuration reference | 2026-08-31 | Neko v2 environment/configuration model |
| [Coolify Docker Compose](https://coolify.io/docs/knowledge-base/docker/compose) | Coolify platform documentation | 2026-08-31 | Compose source-of-truth, environment variables and service exposure model |
| [`CloudBrowser specs`](../) | CloudBrowser source/specs | repository | Current Neko EPR/bitrate and CloudBrowser integration boundary |

## Constraints extracted

- Coolify's Docker Compose file is the source of truth for a Compose deployment;
  generated runtime containers must not become the source file.
- The official coturn image documents host-network operation and a separately
  published relay-port range. This package keeps those settings explicit.
- Neko must remain full ICE (`NEKO_ICELITE=false`) when TURN is configured;
  ICE-lite does not provide the needed TURN-client behavior.
- TURN credentials must be short-lived and issued outside this repository.
- TURN is a media/data relay only; it does not carry CloudBrowser HTTP, CDP,
  cookies or SSO traffic.
