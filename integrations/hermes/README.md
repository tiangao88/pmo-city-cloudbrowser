# Hermes integration

CloudBrowser's supported Hermes entrypoint is the local stdio MCP bridge
installed by this package as `cloudbrowser-hermes-mcp`. It calls only the
authenticated employee routes on the public viewer origin. It cannot select an
owner, slot, browser or generation, and it has no raw CDP, cookie/storage,
network-body, filesystem, process or credential-reading operation.

The former `pmoc-cdp-cloudbrowser` helper was removed from the supported tree.
It connected directly to fleet CDP and exposed unrestricted JavaScript and CDP
helpers, which contradicts the current security boundary.

See [the Hermes skill](cloudbrowser/SKILL.md), the
[configuration example](config.example.yaml), and the versioned
[MCP contract](../../specs/contracts/hermes-mcp/v1/README.md).
