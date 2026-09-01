# Slot supervisor service

The slot supervisor will own owner-bound browser lifecycle, slot assignment,
suspend/wake/recreate, and profile/tab persistence. Its current installability
slice exposes only the bounded health/ready endpoint; lifecycle behavior must
be extracted from `legacy/` through TDD before this service is installable.
