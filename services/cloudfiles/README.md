"""CloudFiles public gateway service."""

The gateway owns the public listing and attachment routes. TinyAuth is an edge
concern; only a validated, server-provided session enters the gateway identity
boundary. Internal downloads traffic remains owner-bound and private.
