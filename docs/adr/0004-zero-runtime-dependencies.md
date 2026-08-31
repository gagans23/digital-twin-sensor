# 0004 — Zero runtime dependencies

**Status:** Accepted

## Context

The install list of a privacy tool is part of its threat model. Every transitive
dependency is code a security team must either read or trust, running on a
workstation with visibility into someone's working day.

## Decision

`dependencies = []`. The sensor, store, redaction, graph, gate and harness use
only the Python standard library. Optional extras — `deep-eval` for the agentic
judges, `encrypted` for encryption at rest, `fuzz` for deeper property testing —
are developer- or opt-in-time only, and the tool runs fully without them.

## Consequences

Some things are written by hand that a library would provide. That cost is real
and accepted; a security team can read this repository end to end in an afternoon,
which is the point.

## Enforced by

CI installs with plain `pip install -e .` and runs the full suite. Any import of a
third-party package outside an optional path breaks that job.

## What would reverse this

A dependency that is itself auditable in an afternoon and removes more risk than
it adds. The bar is deliberately high.
