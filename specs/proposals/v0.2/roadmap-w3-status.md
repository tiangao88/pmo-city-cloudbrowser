# W3 refactor roadmap

This file records the current status imported from the former project. It is
not an approval to deploy the imported implementation.

- W2: complete and accepted.
- W3-1A: queue/identity reconciliation passed.
- W3-1: **PRE-LOGIN CHECKPOINT / NOT QUALIFIED**. Owner-bound source/runtime
  boundaries and local contract coverage exist, but production form mode is
  disabled; the prior form proof is historical only; Authentik currently
  detects MFA but does not submit TOTP or perform a human one-time-code
  handoff; live Authentik closed-shadow qualification is not qualified.
- W3-5: isolated agent-browser PoC complete; not added to live slots.
- W3-7: source/test verified; not deployed by this bootstrap.
- W3-8: documentation/contract work complete; not deployed by this bootstrap.
- W3-2, W3-3, W3-4, W3-6: remain separately gated or open.
- W4: replan after the broker-boundary refactor and the W3-1 acceptance gates.

The final product requirements still require ordinary form login, TOTP
submission, human one-time-code handoff, SSO application identity proof, and
owner-bound recovery. Those requirements are not weakened by the current
milestone status; they simply cannot be claimed as shipped here.
