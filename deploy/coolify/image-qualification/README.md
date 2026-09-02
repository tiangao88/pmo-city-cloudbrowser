# CloudBrowser image qualification records

Step 17 tracks one immutable qualification record per runtime image. These
records are templates until the GitHub Actions build publishes the images and
its digest/provenance evidence is independently checked.

Required services:

- router
- slot-supervisor
- browser
- viewer
- agent-control
- downloads
- credential-broker

For every record, verify the image digest, non-root user, healthcheck, service
startup, and BuildKit provenance/SBOM. Do not put credentials, cookies,
customer data, or raw browser state in these records. The public downloads
route remains `cloudfiles2.dev01.pmo.city`; routing and live qualification are
step 19, not step 17.

The v0.2.0-dev1 release manifest intentionally remains `installable: false`
until all records are complete and the runtime/security acceptance matrix has
been approved.
