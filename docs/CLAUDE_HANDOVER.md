# Claude Handover

Updated 2026-08-31 following the review of `53f4e94`.

Repository: https://github.com/gagans23/digital-twin-sensor

Read this file, `HARDENING_2026_08_31.md`, `../SECURITY_PRIVACY.md`, and `VALIDATION.md` before continuing. This is a local context-sensor prototype, not an enterprise-ready digital twin or a demonstrated productivity intervention.

## What Changed And Why

The review found integration failures: mechanisms existed but runtime paths bypassed them. This release connects the boundaries rather than adding capture depth.

| Change | Why |
| --- | --- |
| Loopback-only dashboard, Host/Origin checks, API session token, asset allowlist | Prevent file traversal and untrusted requests from reaching local data or controls |
| `open_event_store(db, config)` and encrypted learning text | Make encryption govern normal collection, reads, updates, and feedback |
| Fixed encryption migration; missing keys fail closed | A setting is not protection if the next sample is plaintext |
| Title source gated before extraction | Disabled collection must not leave a hidden derived-title path |
| Full purge clears cards/feedback; retention invalidates cards | Derived memory must not survive full deletion |
| Exports enforce unresolved privacy/wrong/stale feedback | A label must change behavior, not just a badge |
| Explicit restriction resolution in UI/API/CLI | Restoring use is deliberate; a positive rating does not override privacy |
| Suppressed aggregates omit topic labels and small support counts | A topic printed under 'withheld' was still disclosed |
| Artifact/token evidence required for sphere merges | App/category agreement incorrectly joined unrelated projects |
| Sphere seeds no longer contain the first event ID | Repeated artifact identity survives oldest-sample expiry |
| Resume reports are descriptive, with exposure unknown | Calendar parity did not prove delivery or withholding |
| Connector manifests included in wheels | Installed packages had zero connectors despite source tests passing |
| Separate fleet/privacy connector renderers; immediate pack rebuild after restrictive feedback | A duplicate function stopped dashboard rendering, and stale UI could still display a previously ready pack |
| Coverage labelled as a heuristic, not fidelity | The score is not calibrated twin accuracy |

## Runtime Contracts

- Use `open_event_store` for runtime event access. Direct `EventStore(..., cipher=...)` is for migration/tests; health may read timing-only summaries without decryption.
- Pass `config=config` to runtime `LearningStore` calls.
- Stored-context exports must call `build_context_pack(..., db_path=db)`. Pure synthetic callers can supply explicit `feedback`. Every production export path supplies its database.
- Unresolved legacy privacy labels with broken identity links block conservatively until reviewed. Do not remove this fallback just to make a pack ready.
- Resolve a reviewed restriction with `digital-twin-sensor feedback resolve --feedback-id ID` or Learning > Resolve restriction. Resolution is timestamped.
- The page supplies an ephemeral `X-DTS-Token` through the JS API helper. A dashboard restart requires a page reload. Remote binding is unsupported.
- Full purge deletes events, cards, and feedback for the subject. Retention removes old events and cached cards but keeps feedback restrictions so expiry cannot weaken consent. Exported copies cannot be recalled.
- Encryption remains optional and partial: timing, app/domain/subject, linkage, and feedback labels remain readable. Key-file fallback is weaker than the OS keychain.
- The graph, DTS, spheres, and query ranker are separate derivations. Packs currently use spheres; graph benefit needs an ablation.

## Verify

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[encrypted]"
python -m unittest discover -s tests
python -m digital_twin_sensor harness --baseline harness/baseline.json --format markdown
node --check digital_twin_sensor/ui_static/app.js
node --test tests/dashboard_ui.test.cjs
python -m compileall -q digital_twin_sensor
git diff --check
```

Build a wheel, install it outside the checkout, and run `scripts/check_installed_package.py`. Source imports do not verify distribution contents. Final results are recorded in the release note.

The collector/dashboard/watchdog/learning LaunchAgents share `~/.digital-twin-sensor/venv`. Reinstall once and restart services; avoid concurrent installers. Preserve depth and privacy settings. Never broaden capture to pass a test.

## Next Build: Reliable Task Resumption

The first vertical slice is now implemented. Read `RESUME_WORKFLOW.md` before extending it. `/api/resume` and the Resume my work view provide gated observations, separate inferred suggestions, redacted/versioned user checkpoints, and explicit request/display/self-reported-outcome records. No new capture permissions, model training, or causal comparison were added. The resume tables participate in encryption migration and purge/retention; session metadata is plaintext. Browser checks covered desktop/mobile and the main flow with synthetic data.

The remaining work below is still open: durable task identity, complete source lineage, measured progress, and prospective experimental design. Do not mistake the new client display acknowledgement for proof of reading or the user outcome for independent productivity measurement.

1. Introduce observation, inference, and confirmed-outcome types with evidence, validity dates, and correction history. Foreground presence does not prove attention or progress.
2. Add coarse coverage states: permitted, unavailable, paused, failed, expired. Missing observation does not prove neglected work.
3. Persist task membership and split/merge corrections. Current deterministic identity stabilizes repeated artifact seeds, not arbitrary regrouping or renames.
4. Show last confirmed state, changes since the last visit, unresolved question, and supporting evidence. Current generic next-action templates are guesses.
5. Build prospective assignment and actual pack-delivery/exposure logging with a separately validated progress endpoint. Historical resume reports must remain non-comparative.
6. Compare against no context, recent activity, and query-only retrieval at fixed model/context budgets. Tune routing only after suitable held-out outcome data exists.

X-SYNTH inspires attention-informed relevance and feedback attribution. This repo implements heuristics and feedback records, not the paper's trained router or reproduced results. A candidate extension is reasoning under permission-limited, incomplete, correctable observation. Novelty and benefit remain unproven.

## Privacy And Writing

No keystrokes, clipboard, camera, microphone, cookies, credentials, or raw cloud traces. Preserve explicit browser/Accessibility/OCR controls. OCR currently uses a transient image file; do not claim it never captures pixels or that crash cleanup is proven. Never publish local traces, settings, or keys.

The user prefers plain, specific, human prose. Explain what happened, why, and what remains unknown. Avoid polished launch slogans and unsupported claims. Keep this handover and the build log current.
