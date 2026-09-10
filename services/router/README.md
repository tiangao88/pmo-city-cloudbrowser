# Router service

The router implements durable queue/session creation, activation, leave, roster,
sliding active-session leases, and owner-bound forwarding. It resolves the
authenticated principal through the identity-link service and adopts a slot
binding through its private supervisor.

The agent relay accepts the operations defined in
[agent-control/v1](../../specs/contracts/agent-control/v1/contract.md).
Credential login forwarding separately mints a signed, expiring, single-use
capability binding the owner, browser generation, site and exact tab. Router
access does not provide vault custody or plaintext credentials.

Implementation: `src/cloudbrowser/router/router_api.py`, `sessions.py`,
`agent_control_forwarder.py`, `credential_broker_forwarder.py`.
See [control-api/v1](../../specs/contracts/control-api/v1/README.md) and
[installation configuration](../../deploy/coolify/README.md).

Source supports a configured slot map; multi-slot deployment and complete
ownership/persistence acceptance must be demonstrated for the candidate release.
See [status](../../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md).
