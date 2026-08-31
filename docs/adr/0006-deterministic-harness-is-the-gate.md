# 0006 — The deterministic harness is the CI gate, not the agents

**Status:** Accepted

## Context

The repository has two evaluation layers: a deterministic harness over a golden
set, and an optional deep-agent layer (`deep_harness.py`) that runs adversarial
judges — a leakage adversary, a resumability judge, a synthesis critic, a gap
analyst. The agentic layer finds classes of problem the scenarios do not
anticipate, which makes it tempting to promote it to the gate.

## Decision

The deterministic harness gates CI. The deep harness is an optional, developer-
invoked judgement layer that never blocks a build and never touches the local
event store — it runs against synthetic fixtures only.

## Consequences

CI stays reproducible and offline: same input, same score, no API key, no spend,
no flake. The agentic layer stays useful precisely because it is allowed to be
noisy and opinionated, which is a bad property for a gate.

## Enforced by

`.github/workflows/ci.yml` runs `digital-twin-sensor harness` only.
`tests/test_deep_harness.py` asserts the deep layer degrades cleanly when its
optional dependency is absent.

## What would reverse this

Agentic judges with a measured false-positive rate low enough to gate on. That
number does not exist yet, and inventing it would repeat the mistake recorded in
ADR 0008.
