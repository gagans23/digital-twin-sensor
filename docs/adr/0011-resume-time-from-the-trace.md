# 0011 — Measure resume time from the trace, and refuse to compare a thin sample

**Status:** Accepted

## Context

Task-resume time is the benefit this project promises and has never measured
(`docs/VALIDATION.md` V2). The obvious way to collect it is to ask the operator
to mark interruptions and resumptions. That fails in the ordinary way:
self-reporting during an interruption is exactly the moment nobody wants to
stop and log something, so the data would be sparse and biased toward the calm
interruptions.

The trace already contains the signal. A gap in attention is a proxy for an
interruption, and a return to the artefact cluster that was active before the
gap is a proxy for resumption.

## Decision

Derive resume events from the existing store, with no new collection:

- **work is a run**, not an event: the collector samples every few seconds, so
  dwell is accumulated across consecutive attention on the same cluster. Judging
  a single event's dwell found nothing at all against a real 11,783-event trace,
  because no sample ever cleared the bar;
- an **interruption** is a gap longer than `gap_minutes` (default 15 — shorter
  is thinking, not interruption);
- the **task** being returned to is the last *substantive* activity before the
  gap, not merely the last event, so a five-second glance is not mistaken for
  what someone was doing;
- a **resume** is the first return to that cluster lasting at least
  `substantive_seconds` (default 60), so a glance at a window that is
  immediately abandoned does not count;
- once an episode resolves, scanning continues after the resumption, so a pause
  inside the resumed stretch is not charged to the same interruption twice.

Conditions alternate in day-length blocks derived from the ordinal date, so
which condition applied on a given day is fixed before the day starts and
cannot be reassigned after seeing the result.

The report gives a **distribution**, never a mean: resume time is long-tailed
and the tail is the interesting part. Below `MIN_EVENTS_PER_CONDITION` in either
condition the tool prints both distributions and **refuses to print a
comparison**, saying why.

## Consequences

The measurement collects itself from an ordinary fortnight of work. It is also
weaker than a trial, in ways the output states every time it runs: one subject,
unblindable, and interruptions inferred rather than observed. An unattended
machine will read as an interruption, which inflates the count of long gaps.

A zero result must explain itself. The report says which stage produced nothing
— no events, no substantive run, no gap, no known prior task, or a genuine
never-returned — and prints the detector's own counts. An empty table that could
equally mean "never interrupted" or "detector broken" is worse than no table.

## Enforced by

`tests/test_resume_study.py` — including the refusal to compare on a thin
sample, that a glance is not a resume, and that the blinding confound is named
in every report.

## What would reverse this

Direct instrumentation of the applications being resumed, which would replace
the gap proxy with an observed event. That is a much larger integration and is
not worth it before the proxy has produced a first number.
