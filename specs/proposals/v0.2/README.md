# CloudBrowser v0.2 proposal

This is mutable work under review. It captures the generic Credential Broker,
CloudFiles target, development plan, product boundaries, security model,
current agent API, and W3 status.

The current CloudFiles target is frozen in `89-cloudfiles-product-requirement.md`.
The recommended new-structure implementation plan is in
`90-cloudfiles-development-plan.md`. These documents freeze the desired product
outcome and development approach; they do not authorize live deployment.

**Phase 0 is the current pre-implementation gate.** It covers public-contract
review, the route/threat matrix, and red security tests. Phase 1 begins only
when Phase 0's exit criteria are met.

The new public contract is `specs/contracts/cloudfiles/v1/README.md`.
A concise phase-by-phase map is in `91-cloudfiles-delivery-phases.md`.

Exit criteria before implementation:

- product and trust boundaries approved;
- broker capability and profile binding defined;
- restricted browser-control contract versioned;
- adversarial security tests written and red;
- migration and rollback plan accepted;
- no direct agent or slot access to credential material.
