# CloudBrowser TURN relay template

This design-only coturn template belongs to the CloudBrowser project. It
requires host networking and has no HTTP proxy route. See the [TURN runbook](../runbook.md)
for the approval, firewall, certificate, credential and verification gates.

The official coturn image currently documents `coturn/coturn:4.17.2-r0` and
host-network operation. Production must still record the resolved digest and
reconfirm the tag before deployment.
