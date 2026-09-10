# CloudBrowser source

`cloudbrowser/` contains the implemented router, browser lifecycle and actions,
viewer relay, agent-control boundary, credential broker/custody, CloudFiles,
downloads and identity-link services. The tree is no longer an extraction stub.

Service entrypoints under `services/` supply configuration and dependencies.
Keep credential custody and broker capabilities separate from agent operations;
preserve the versioned interfaces under `specs/contracts/`. Behavior changes
follow the contract/security regression workflow in
[CONTRIBUTING.md](../CONTRIBUTING.md).

Prior implementation under `legacy/` remains migration/reference evidence.
Use the [service map](../services/README.md) and
[status register](../specs/proposals/v0.2/IMPLEMENTATION-STATUS.md) to find
current behavior and remaining user-journey acceptance.
