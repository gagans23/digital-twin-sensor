# 0003 — Redact before the write, not on read

**Status:** Accepted

## Context

Redaction can happen at three points: on capture, on storage, or on export.
Export-time redaction is the common choice because it is easiest to add later and
keeps the raw data available "just in case".

"Just in case" is the problem. A local database holding raw window titles from a
banking workstation is a liability whatever the export layer does, and the export
layer is exactly the code most likely to grow a bypass under delivery pressure.

## Decision

Text passes through `redact_text` before it reaches SQLite. Emails, phone
numbers, national IDs, card candidates (Luhn-checked), IPs, URLs beyond their
host, and known secret formats are masked at capture time. What is written to
disk is already redacted; the store never holds the raw string.

## Consequences

Redaction bugs destroy signal permanently rather than leaking it — the safer
direction of failure. Findings are counted per event so the loss is visible and
measurable instead of silent.

## Enforced by

`tests/test_redaction.py`, `tests/test_fuzz_leak_gate.py` (generated hostile
inputs), and the harness leak canaries, which fail the build on any escape.

## What would reverse this

Nothing. Later redaction is strictly weaker; the only defensible change is adding
patterns.
