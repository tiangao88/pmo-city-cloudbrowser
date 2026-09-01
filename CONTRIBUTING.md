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

## Pull requests

A PR must state:

- product/specification version affected;
- requirement and contract IDs;
- security and migration impact;
- tests run and their result;
- rollback behavior for installation changes.

A green CI run and CODEOWNERS review are required before merging.
