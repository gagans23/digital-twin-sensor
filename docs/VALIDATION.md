# Validation plan

Everything in this repository that is asserted rather than measured, with the
specific evidence that would settle it. A disclaimer says a number is unproven.
A plan says what would prove it, and can be collected on.

Nothing here is scheduled. This is a list of debts, not a roadmap.

---

## V1 — The confidence weights

**Claim as it stands.** Theme confidence is `0.65 * breadth + 0.35 * depth`
(`synthesis.py::_confidence`). The weights were chosen by hand in an afternoon
and have never been fitted. See ADR 0008.

**Why it matters.** The formula sits in a repository that maps ten papers to
design decisions, so an unlabelled number reads as inherited. Downstream, the
score influences which themes a reader trusts.

**What would settle it.** The sensor already collects feedback labels
(`learning.py`: useful / wrong / stale / too_broad / too_private /
missing_context). Those are the labels.

**Acceptance criteria.**

- At least 200 labelled theme judgements, from at least 3 subjects, over at least
  4 weeks — so the fit is not one person's fortnight.
- Fit breadth and depth weights by logistic regression against `useful`.
- Report held-out AUC against a stratified split. Below 0.60, the formula is
  replaced by a flat prior, not retuned until it passes.
- Compare against two nulls: breadth alone, and a constant. A formula that does
  not beat breadth alone should be deleted, not defended.

**Until then.** The label stays in the docstring, the docs, the README and the
public case study, and `tests/test_synthesis.py` fails if it is removed.

---

## V2 — Task-resume time

**Claim as it stands.** None. This is the product's core promised benefit and it
is untested — stated as untested in the essay, the README and the gaps table.

**What would settle it.** A measured comparison of time-to-productive-resume
after an interruption, with and without a context pack.

**The descriptive instrument exists; the experiment does not.**
`digital-twin-sensor resume-study` derives observable returns from local traces.
It cannot establish pack delivery or productive resumption. The August 31 review
found that calendar labels were being treated as exposure. Reports now mark
exposure unknown and never print a treatment comparison, regardless of sample
size. Prospective assignment, actual delivery/withholding, and an independent
progress endpoint are required before estimating benefit:

```bash
digital-twin-sensor resume-study --days 14
digital-twin-sensor resume-study --days 14 --format json --output resume-study.json
```

**Acceptance criteria.**

- One operator, one real function, at least 4 weeks of ordinary work.
- Resume events timestamped from interruption to first substantive action on the
  prior task, with the pack shown or withheld in alternating blocks.
- Report the distribution, not a mean: resume time is long-tailed and the tail is
  the interesting part.
- n=1 is a case study and must be labelled one. It is still worth more than the
  zero measurements that exist today.

**Known confound.** The operator knows which condition they are in. Blinding is
not possible for a tool you can see, and pretending otherwise would be worse than
naming it. Every report restates this, so a number cannot travel without it.

---

## V3 — Redaction recall

**Claim as it stands.** Redaction masks emails, phone numbers, national IDs,
Luhn-valid cards, IPs, URL paths and prefixed secrets before storage. Recall
against real workstation titles is unmeasured.

**What would settle it.** A labelled corpus of window titles with sensitive spans
marked, scored for recall and precision. That corpus does not exist and cannot be
manufactured honestly — synthetic titles measure the generator, not the world.

**Acceptance criteria.**

- At least 2,000 real titles from at least 3 machines, labelled by their owners,
  never leaving those machines: the scoring script runs locally and reports only
  aggregate counts.
- Report recall per category. Any category below 0.95 gets a pattern change or an
  explicit note in the threat model.

**Interim measure.** The property tests
(`tests/test_fuzz_leak_gate.py`) generate hostile inputs and have found two real
evasions so far. That is a lower bound on the gap, not a substitute for V3.

---

## V4 — The aggregation floor in practice

**Claim as it stands.** A `min_subjects` floor of 5 (never below 2) prevents a
theme from resolving to an individual (ADR 0007).

**What would settle it.** An adversarial attempt at re-identification by someone
who knows the team composition — the realistic attacker, not a stranger.

**Acceptance criteria.**

- Themes from a team of at least 8, handed to a reviewer who knows the roster.
- Score attribution accuracy. Anything above chance means the floor needs to rise
  or the themes need coarsening.

---

## V5 — The deep-agent judges

**Claim as it stands.** The adversarial judges surface issues the deterministic
scenarios do not. Their false-positive rate is unknown, which is why they do not
gate CI (ADR 0006).

**Acceptance criteria for promotion to a gate.**

- At least 50 judge findings triaged by hand into real / not real.
- False-positive rate below 0.10 across two model versions, so the gate does not
  move when the model does.

Until that exists, promoting them would repeat V1's mistake in a new place.
