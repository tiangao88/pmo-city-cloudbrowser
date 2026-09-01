# Downloads service

The downloads service will own durable per-user download access. Its current
installability slice exposes only the bounded health/ready endpoint; download
authorization and persistence contracts must be implemented before this
service is installable.
