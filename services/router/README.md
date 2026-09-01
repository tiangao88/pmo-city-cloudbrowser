# Router service

The router service owns request routing and queue orchestration. Its current
installability slice exposes only the bounded health/ready endpoint; the
owner-bound control API must be extracted behind `control-api/v1` before this
service is installable.
