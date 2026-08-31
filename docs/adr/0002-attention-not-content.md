# 0002 — Capture attention and sequence, not content

**Status:** Accepted

## Context

The undocumented half of institutional knowledge is reasoning: what someone
checked, in what order, what they dismissed early. The tempting way to capture
that is to record everything — screen, keystrokes, clipboard — and mine it later.

That approach fails twice. It is unacceptable to the people being observed, which
means it never runs long enough to produce anything; and it collects vastly more
sensitive material than the signal requires. *X-SYNTH* (arXiv 2605.15505) argues
the opposite direction: enterprise context can be synthesised from observed
digital attention rather than from authored or captured content.

## Decision

Collect what was attended to and in what sequence: application, window title,
artefact identity, dwell, transitions. Never keystrokes, never screenshots, never
clipboard. Content is out of scope by construction, not by configuration.

## Consequences

The signal is thinner than a full recording and provably less invasive. Several
questions the system could otherwise answer are permanently out of reach; that is
the trade, and it is the reason anyone would run this on their own machine.

## Enforced by

`tests/test_attention_depth.py`, `tests/test_controls.py`; the gate denies
`keystrokes`, `clipboard` and `screenshots` as standing decisions in
`context_pack.py::_base_decisions`.

## What would reverse this

Nothing short of a different product. A content recorder is a different tool with
a different threat model and should be named differently.
