# Viewer service

The viewer will own user-facing browser display and input forwarding. Its
current installability slice exposes only the bounded health/ready endpoint;
the authenticated viewer contract must be implemented before this service is
installable.
