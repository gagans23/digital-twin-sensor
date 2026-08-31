# 0007 — Count-based k-anonymity floor in synthesis

**Status:** Accepted. The floor stands; the trust model it assumed is superseded by [0012](0012-secure-aggregation-trust-model.md), which stops the aggregator holding per-subject spheres in the first place.

## Context

The synthesis layer folds per-subject working spheres into team-level themes.
Aggregation is where a privacy-preserving tool usually stops being one: a theme
drawn from a single person's activity is that person's activity with a plural
noun in front of it.

## Decision

Apply Sweeney's k-anonymity (2002) as a hard floor: a theme is only emitted when
at least `min_subjects` distinct subjects contribute (default 5, floor 2).
Below-floor themes are withheld *and counted*, so the summary reports how much it
is not telling you. Subject identity is carried as an opaque
`sha256[:12]` key that never resolves back to a person through the export.

## Consequences

Small teams get thin summaries. That is correct behaviour, not a limitation to
tune away — and the withheld-count makes the thinness legible rather than
invisible.

## Enforced by

`tests/test_synthesis.py`, including below-floor withholding and the opacity of
`subject_key`.

## What would reverse this

A stronger formal guarantee — differential privacy on the aggregate — would
supersede this, not relax it.
