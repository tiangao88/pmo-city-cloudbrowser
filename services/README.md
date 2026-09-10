# CloudBrowser runtime services

The source defines nine application services, plus ClamAV. The service map
below describes responsibility, not current release qualification. See
[implementation status](../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md).

| Service | Responsibility | Main source |
| --- | --- | --- |
| router | Queue/session lifecycle, owner-derived routing, agent forwarding, signed login capabilities | `src/cloudbrowser/router/` |
| slot-supervisor | Wake, stop, suspend, recreate and binding adoption | `src/cloudbrowser/browser_slots/supervisor.py` |
| browser | Chromium process/profile, exact-target actions, private broker capabilities, completed-download watcher | `src/cloudbrowser/browser_service.py`, `browser_slots/` |
| viewer | Authenticated queue/roster/control HTML and router relay | `src/cloudbrowser/viewer/` |
| agent-control | Owner/generation checks and bounded tab/page operations | `src/cloudbrowser/agent_control.py` |
| credential-broker | Deterministic login, private credential custody, replay/idempotency/deadline enforcement | `src/cloudbrowser/credential_broker/` |
| cloudfiles | Public authenticated file gateway and private scan-before-publish ingest | `src/cloudbrowser/cloudfiles/` |
| downloads | Private durable per-principal file listing/retrieval | `src/cloudbrowser/downloads/` |
| identity-link | Durable mapping from trusted SSO subject to opaque PMO principal | `src/cloudbrowser/identity_link_service.py` |

Entrypoints configure dependencies; domain and policy behavior live under
`src/cloudbrowser/`. See each service README and the
[Compose guide](../deploy/coolify/README.md) for configuration.

Browser downloads flow through the watcher and private ingest receiver into
scan/quarantine policy and durable owner storage. CloudFiles supplies the public
HTML/attachment surface and calls the internal downloads service with a trusted,
server-derived binding. Both services and ingest wiring are present in source.

A viewer shell and broker capability implementation do not establish a complete
employee journey. Live streaming/takeover, consent continuity, profile switching,
and current-image qualification are explicit roadmap work.
