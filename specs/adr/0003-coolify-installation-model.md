# ADR-0003: Reproducible Coolify installation bundles

- Status: Accepted as repository bootstrap policy
- Date: 2026-09-01

A CloudBrowser release is installed as a pinned Compose bundle through Coolify.
Every installation has an explicit instance name and isolated resource
namespace. A parallel version must not reuse networks, volumes, hostnames,
secrets namespaces, browser profiles, router state, broker state, or downloads
storage. UI-only changes are documented as exceptions and must not be needed
for a clean installation.
