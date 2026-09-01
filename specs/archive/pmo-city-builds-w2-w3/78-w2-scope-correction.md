# W2 scope correction — advisory overlay

> **Decision record — 2026-08-28/29.** W2 was a binary all-green pilot gate.
> Every retained W2 exit row is now green, evidence-linked, and accepted by
> Tigo. Deliberate W3 carry-over is not a yellow W2 item.

Detailed evidence and historical status remain in the existing W2 documents. This overlay defines the corrected boundary.

## W3 items removed from the W2 exit gate

- **W3-1:** strict authenticated-surface continuity and broker auto-relogin after restart, wake, or container recreate.
- **W3-2:** dedicated A2/IdP client, if still needed, and expanded audit metadata beyond the W2-required non-secret record.
- **W3-3:** screen-follow.
- **W3-4:** native neko chat agent.
- **W3-5:** `agent-browser` + browser-use productization evaluation.
- **W3-6:** broader CRMOC/transversal service-browser rollout.
- **W3-7:** optional tab-loss/lifecycle hardening.
- **W3-8:** operational/audit expansion and W4 preparation.

## W2 status

W2 is **COMPLETE**: all retained W2 requirements are green, including pilot
acceptance, soak evidence, and Tigo SME sign-off. W3 delivery cannot close a
W2 blocker.

## Historical closure rows

The current detailed status records D1, D9, and D14 as green W2 closure rows;
their evidence is in `79-d1-pilot-evidence.md`, `22-w2-progress.md`, and
`80-d14-crm-evidence.md`. D3/D15 is **green and closed for W2**. D13 is W3-3,
not a W2 blocker. Strict authenticated-surface continuity is W3-1.

## Authoritative register

See `08-roadmap.md` for the corrected roadmap and `28-w3-scope.md` for W3 acceptance criteria.
