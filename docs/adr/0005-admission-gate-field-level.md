# 0005 — Field-level admission gate on every export

**Status:** Accepted

## Context

A context pack that says "here is what I know" is unauditable. The person
observed cannot tell what was considered and withheld, and the receiving agent
cannot tell whether an absent field was missing or refused.

## Decision

Every export passes a Memory Admission Gate that emits a decision per field —
`allow`, `summarize`, `generalize`, `mask` or `deny` — each with a reason string.
Denials are exported as denials with their reasons, not silently dropped. Counts
are attached to the pack so the shape of the refusal is visible at a glance.

## Consequences

Packs are larger and the code is more tedious, because every new field must be
declared and justified. That tedium is the product: an agent that cannot say what
it did not have cannot be trusted with what it did.

## Enforced by

`tests/test_context_pack.py`, `tests/test_controls.py`; harness scenarios assert
gate counts as well as recall, so a gate that quietly stops denying breaks the
build even when recall improves.

## What would reverse this

Nothing. Cheaper gates have been considered and each removed the auditability
that justifies the export.
