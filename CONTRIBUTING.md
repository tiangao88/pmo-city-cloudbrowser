# Contributing

## Workflow

1. Start from `main` for a new feature, or from the applicable `release/X.Y`
   branch for a maintenance fix.
2. Put specification changes in `specs/proposals/` first. Identify impacted
   requirement and contract IDs.
3. Follow RED → GREEN → REFACTOR for behavior changes. No production code
   without a failing test that demonstrates the required behavior.
4. Run `make check` before opening a pull request.
5. Never commit secrets, live browser state, customer data, generated traces,
   or unredacted operational evidence.
6. Keep deployment changes separate from application changes where possible.

## Documentation and acceptance

Use the current product PRD, roadmap and implementation-status register linked
from the root README. Update requirements before changing scope, the roadmap
when sequencing changes, and status after demonstrating behavior. Record source
SHA, local test results/skips, qualified image digests and deployed user
acceptance separately. Historical reports are not evidence for a newer build.
Do not rewrite immutable baselines or imported evidence. Keep service READMEs
aligned with implemented boundaries, rather than duplicating the roadmap.

For documentation-only edits, run the documentation/contract checks and
validators plus a relative-link/diff check. A full runtime run is useful for a
takeover baseline but is not proof supplied by the prose change.

## Pull requests

A PR must state:

- product/specification version affected;
- requirement and contract IDs;
- security and migration impact;
- tests run and their result;
- rollback behavior for installation changes.

A green CI run and CODEOWNERS review are required before merging.
