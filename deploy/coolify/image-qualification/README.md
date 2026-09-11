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
- cloudfiles
- identity-link

For every record, verify the image digest, non-root user, healthcheck, service
startup, and BuildKit provenance/SBOM. Do not put credentials, cookies,
customer data, or raw browser state in these records. The public downloads
route remains `cloudfiles2.dev01.pmo.city`; routing and live qualification are
step 19 / Phase 6, not step 17.

All nine records contain `status: passed` evidence from qualification run
`34603628801` at commit
`8e455b4efbbde723c26c47879da1b339ca3835b5`, including `cloudfiles` and
`identity-link`. CI published every image, verified provenance/SBOM and runtime
health, and the release change synchronized all digests and provenance
atomically. Step 19 / Phase 6 still covers deployment and runtime/security
qualification as a separate outcome.
