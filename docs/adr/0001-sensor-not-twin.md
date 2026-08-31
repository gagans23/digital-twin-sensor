# 0001 — Call it a sensor; refuse to claim a faithful twin

**Status:** Accepted

## Context

The obvious product framing for this work is a digital twin: a model that stands
in for a person and can be asked questions on their behalf. That framing sells,
and it is what most of the adjacent literature is chasing.

It is also, on the current evidence, wrong. *Digital Twins as Funhouse Mirrors*
(arXiv 2509.19088) shows LLM-based human twins correlate weakly with the people
they model and distort systematically — not randomly, which would be tolerable,
but in consistent directions. *Trust Calibration in Twin Agents* (arXiv
2605.19838) names the specific gaps that open the moment an agent speaks *as*
someone: schema gaps, epistemic gaps, model-artefact gaps.

Neither paper proposes a capability. Both constrain what may be claimed.

## Decision

The system is a sensor. It observes attention, exports evidence, and never
speaks as the person observed. Every export carries confidence, evidence age and
attribution so a reader can tell what the claim rests on. No output is phrased in
the first person of the subject.

## Consequences

The product is harder to demo and easier to defend. It also means the interesting
surface is what the system *declines* to assert, which is where most of the
engineering effort has gone.

## Enforced by

`tests/test_context_pack.py` (attribution and confidence present on every pack),
`digital_twin_sensor/context_pack.py::_base_decisions` (identity denied by
default).

## What would reverse this

Replication showing twin fidelity high enough to act on for a *specific* bounded
task — not in general. The reversal would be scoped to that task, not to the
framing.
