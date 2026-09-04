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

The eight original Step-17 records are complete and marked `status: passed`;
their immutable digests are recorded in the v0.2.0-dev1 release manifest. The
`cloudfiles` and `identity-link` records are added by the CloudFiles Phase 5
implementation. They remain `status: pending` until CI publishes each image,
verifies provenance/SBOM and runtime health, and the real digests are pinned in
the release manifest. Step 19 / Phase 6 still covers deployment and
runtime/security qualification and requires separate approval.
