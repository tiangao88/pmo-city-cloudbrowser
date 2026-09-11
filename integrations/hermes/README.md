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

## Agent and dashboard containers

MCP configuration belongs to the selected Hermes profile. Select
`cloudbrowser-test` in the dashboard to use the test integration; the default
profile does not inherit its servers or authentication.

Every process using that profile must be able to execute the configured bridge.
Sharing the Hermes home volume does not imply that `/opt/data` is shared. On
dev01, the agent and dashboard have different `/opt/data` volumes, so an agent
virtual environment under that path cannot serve dashboard chats.

The dev01 test profile therefore stores the qualified, standard-library-only
`hermes_mcp.py` in a versioned `runtimes/cloudbrowser-<source-hash>/` directory
inside the shared profile. Its MCP command is `/usr/bin/python3`, with the
absolute script path as its argument. Profile secret references remain intact.
Validate tool discovery and an authenticated task from each execution container.
After changing configuration, start a fresh chat so it reloads MCP tools.
