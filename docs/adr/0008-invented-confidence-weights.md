# 0008 — Ship the confidence formula labelled as an unvalidated prior

**Status:** Accepted, pending validation

## Context

The synthesis layer scores theme confidence as `0.65 * breadth + 0.35 * depth`.
Those weights were chosen by hand in an afternoon. They have never been fitted
against data, because no labelled data existed when they were written.

Sitting in a repository that carefully maps ten papers to design decisions, an
unattributed formula reads as inherited. That is the exact mechanism by which an
assumption becomes a finding: stated confidently in a credible context, repeated,
never questioned. Sweeney (2002) is cited for the aggregation floor in ADR 0007
and for nothing else — in particular, not for these weights.

## Decision

Keep the formula, because a scored output is more useful than an unscored one,
and label it as an unvalidated prior everywhere it appears: the docstring on
`_confidence`, `docs/UNDER_THE_HOOD.md`, the README, and the public case study.
Track its validation as an open commitment with acceptance criteria — see
`docs/VALIDATION.md`.

## Consequences

The repository carries a visible admission of a weak spot. That is preferable to
carrying an invisible one, and it makes the validation debt collectable.

## Enforced by

`tests/test_synthesis.py` asserts the provenance note stays in the docstring, so
deleting the disclaimer fails the build.

## What would reverse this

Fitting the weights against collected feedback labels per `docs/VALIDATION.md`,
after which this ADR is superseded by one recording the fitted values and their
sample size.
