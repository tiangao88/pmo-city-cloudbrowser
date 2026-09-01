# CloudBrowser source extraction

The new `src/` and `services/` tree is intentionally seeded with boundaries,
not copied production logic. Runtime extraction must follow TDD: create a
failing contract/security test, implement the smallest behavior, then move
code out of `legacy/` only after the test passes.
