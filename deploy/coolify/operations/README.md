# Coolify release operations

Scripts in this directory will own backup, install, health verification, and
rollback once the installable release contract is approved. Operations must
accept an explicit instance ID and release manifest; no script may infer or
reuse another installation's volumes.
