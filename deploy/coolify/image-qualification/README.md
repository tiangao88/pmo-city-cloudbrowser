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

For every record, verify the image digest, non-root user, healthcheck, service
startup, and BuildKit provenance/SBOM. Do not put credentials, cookies,
customer data, or raw browser state in these records. The public downloads
route remains `cloudfiles2.dev01.pmo.city`; routing and live qualification are
step 19 / Phase 6, not step 17.

The seven original Step-17 records are complete and marked `status: passed`;
their immutable digests are recorded in the v0.2.0-dev1 release manifest. The
`cloudfiles` record is added by the CloudFiles Phase 5 image qualification and
stays `status: pending` until that CI run publishes the image and its digest
is pinned in the release manifest. The release is installable at the
source/package level once every digest is pinned. Step 19 / Phase 6 still
covers deployment and runtime/security qualification and requires separate
approval.
