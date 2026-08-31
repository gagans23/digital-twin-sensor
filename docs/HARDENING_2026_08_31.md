# Hardening Release: 31 August 2026

This release responds to the review of `53f4e94`. Privacy controls, encryption, feedback, and evaluation existed separately but did not consistently govern the running product. The implementation and reasons are mapped in `CLAUDE_HANDOVER.md`.

## Verification

- 152 Python tests pass with cryptography available, including normal collection after encryption migration and rejection of writes from a stale plaintext connection.
- Four dependency-free JavaScript tests pass: separate connector renderers, explicit confirmation/cancellation, immediate restrictive-feedback rebuild, and the blocked-state explanation.
- Five deterministic harness scenarios pass without baseline regression; the longer `FUZZ_ITERATIONS=5000` run also passes. These are synthetic checks, not real-world privacy-recall estimates.
- Wheel and sdist build successfully. Installed-wheel smoke outside the checkout finds three connector manifests and all three UI assets.
- Browser verification with synthetic data covered initial rendering, ready-to-blocked feedback, cleared admitted evidence, and the Learning ledger. It exposed a duplicate JavaScript renderer, which was fixed. Native confirmation stalled the browser test; it was replaced with an inline confirm/cancel step tested by the JavaScript suite. Final visual/responsive re-verification remains outstanding.
- The live shared environment was updated once, then collector, dashboard, learning maintenance, and watchdog were restored. All 36 installed runtime/assets files match the source. The configuration file is byte-for-byte unchanged; optional encryption remains disabled.
- Live `/api/health` and `/api/overview` return HTTP 200 with the session header; unauthenticated health access returns 403. The sample was 12 seconds old at verification. Health reported 12 ready checks, the standing Automation Permissions advisory, and no blocked checks. That advisory does not verify permission for every app or prove OCR captured content.

Only code, synthetic tests, and documentation are published. No local traces, configuration, or keys are included.

## Deliberate Limits

This release does not establish productivity improvement, learned routing, eye attention, enterprise RBAC, remote fleet control, complete entity resolution, or full-database encryption. Retention preserves feedback restrictions; full purge removes all local subject events, cards, and feedback. Previously exported files and backups are outside database deletion.

Unknown purposes are rejected, but a recognized purpose is still a declaration rather than a complete enterprise purpose/recipient policy matrix. Current sphere identity stabilizes a repeated artifact seed, not every regrouping. The OCR helper's transient-image cleanup needs separate crash testing. Pattern-based redaction has unmeasured real-world recall. Sampled foreground dwell is not verified human attention.

## Next Milestone

One reliable task-resume workflow: observed facts, inferred membership, and confirmed outcomes shown separately, with persistent corrections and a prospective exposure ledger. See the handover for the sequence and experiment boundaries.
