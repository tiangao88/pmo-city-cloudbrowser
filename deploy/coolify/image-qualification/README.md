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

All nine records retain `status: passed` evidence from prior qualification run
`34402569940` at commit
`50ce1984448ddf79621d4114f81c6a2b2b83d5fa`, including `cloudfiles` and
`identity-link`. Those records and their immutable digests prove only that
prior source state; they do not qualify the current source and must not be used
to mark the current release installable. After the current commit is built, CI
must publish every image, verify provenance/SBOM and runtime health, replace all
retained digests and provenance atomically, and rerun the gates. Step 19 / Phase
6 still covers deployment and runtime/security qualification and requires
separate approval.
