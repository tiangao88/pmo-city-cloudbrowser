# Slot supervisor service

The slot supervisor owns the owner-bound browser lifecycle, slot assignment,
suspend/wake/recreate, and profile/tab persistence. The first extracted slice
is `cloudbrowser.browser_slots.lifecycle.OwnerBoundLifecycle`: it is state-only,
transport-agnostic, and has no dependency on the legacy scripts or credential
handling paths.

The service image currently exposes the bounded health/ready endpoint. Chrome
and CDP transport will be added behind separate interfaces and acceptance tests;
the legacy runtime remains migration/reference material only.
