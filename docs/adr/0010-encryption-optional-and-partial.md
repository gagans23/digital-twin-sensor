# 0010 — Encryption at rest is optional and deliberately partial

**Status:** Accepted

## Context

Encrypting the local ledger protects against a stolen disk or a curious process
reading the SQLite file. Encrypting *everything* would also break every query the
tool needs to run locally — time-window filters, dwell sums, domain grouping —
and would force either a full table scan per query or a decrypted index, which
returns the risk by another door.

## Decision

Encrypt `title`, `artifact` and `metadata` with AES-256-GCM under the `encrypted`
extra, keyed from the OS keyring with a 0600 keyfile fallback that warns loudly.
Leave `ts_start`, `ts_end`, `dwell_seconds`, `domain`, `app` and `subject_id`
in plaintext, and say so out loud rather than implying whole-database encryption.
Migration is idempotent and resumable.

## Consequences

An attacker with the database file learns *when* the subject worked, in which
application and broad domain, and for how long — a real disclosure, documented in
`docs/THREAT_MODEL.md`. They do not learn what was worked on. Anyone who needs
the timing metadata protected too should encrypt the volume.

## Enforced by

`tests/test_crypto.py`, whose `BoundaryTests` assert exactly which columns remain
plaintext, so silently encrypting more (or less) fails the build.

## What would reverse this

A local query layer that runs over encrypted timing metadata without a plaintext
index. Then the boundary moves and this ADR is superseded.
