# 0012 — Aggregate under masks, and derive confidence instead of choosing it

**Status:** Accepted. Supersedes the trust model implied by [0007](0007-count-based-aggregation-floor.md); retires the invented weights in [0008](0008-invented-confidence-weights.md) on this path.

## Context

ADR 0007 put a count-based k-anonymity floor on collective synthesis: a theme is
emitted only when enough distinct subjects support it. That is a sound rule and
it stays. It is also an answer to the second-most-important question.

`synthesize_collective` took `bundles` of `{subject_key, activities}`. Whoever
ran it therefore held **every subject's working spheres in the clear**. The floor
governed what was published; nothing governed what was collected. For the
adversary `docs/THREAT_MODEL.md` takes most seriously — the employer who
controls the deployment — that is the entire game, and a floor applied after the
fact does not touch it.

Two further problems followed from framing this as anonymity rather than as
aggregation:

**Composition.** Sweeney's k-anonymity assumes a single static release. This is a
repeatable query interface: run it Monday with six people, run it Tuesday with
the same six minus one, and diff the output. That is a composition attack (Ganta
et al., KDD 2008). A floor has no notion of accumulated exposure. Exact withheld
counts leaked in the same way.

**The wrong problem name.** What this layer computes is *private heavy hitters
over a population* — the same shape as federated out-of-vocabulary word
discovery, deployed at 15 million participants (Zhu et al. 2020; Gboard OOV,
2024). Naming it correctly shows what is missing, and shows that the deployed
solutions assume population sizes this product does not have at team scale.

## Decision

**Change what crosses the wire.** A client emits a fixed-width vector of counts
over a *declared* theme vocabulary, blinded with pairwise masks derived from a
cohort secret the aggregator does not hold. Masks cancel exactly when the whole
cohort is summed. The aggregator recovers totals and never holds a readable
per-subject contribution. The k-floor from ADR 0007 still applies, now to those
totals.

**Declare the countable units.** The vocabulary is an allowlist with a
description per theme and a digest pinned into every output — the same guarantee
connector manifests give for fields (ADR 0009). Work nobody declared cannot be
counted. The cost is real: you only find what you thought to name. Open-vocabulary
discovery is a trie-based heavy-hitter problem and is deferred, not solved.

**Derive confidence.** Share of cohort with a Wilson interval. The uncertainty in
"how much of this cohort worked on this theme" is a property of the count and the
cohort size. It does not need fitting, and inventing weights for it was the
mistake ADR 0008 recorded. The secure path does not use those weights.

**Band the suppression count.** An exact count of withheld themes is itself
disclosive on a small cohort.

**Leave differential privacy off by default.** This is the finding worth keeping:
*the right mechanism depends on cohort size, and this product's target is the
size where local DP does not work.* Gboard runs ε=10 locally over 500,000 users
per trie layer to reach ε_central ≈ 0.3. At a team of ten, the noise required for
a meaningful epsilon swamps the signal — you would publish randomness with error
bars. Secure aggregation is the stronger practical protection at that scale, so
noise is available (`epsilon=`) and off unless a cohort is large enough to carry
it.

| Tier | Cohort | Mechanism that actually fits |
| --- | --- | --- |
| Team | 5–50 | Secure aggregation + output floor. No noise. |
| Department | 100s | Secure aggregation + noised counts, budget-tracked |
| Institution / sector | 1,000s+ | Shuffle-DP with trie-based discovery |

## Consequences

The privacy claim becomes structural rather than procedural: it holds because
the aggregator cannot read a contribution, not because it promises not to look.

The honest limits, stated in the module and enforced by tests:

- **No dropout resilience.** One missing member and the masks do not cancel, so
  no total is recoverable. `secure_sum` refuses rather than returning a plausible
  wrong number. Recovery needs Diffie-Hellman with secret sharing (Bonawitz et
  al.), which needs a crypto dependency this package does not have (ADR 0004).
- **The cohort secret is symmetric.** It defends against the aggregator, not
  against a cohort member who can already derive their own masks.
- **Aggregator-added noise is central DP.** It assumes the aggregator adds what
  it says. Distributed noise is the next step.
- **This is not anonymity.** It is pseudonymous aggregation with a published
  floor, and the docs now say so.

**No CLI command ships with this.** Cohort formation, secret distribution and
round coordination are unsolved, and a command implying otherwise would be
exactly the failure this repository argues against — a mechanism that looks
finished because its documented half is. The library is complete and tested; the
transport is not built.

## Enforced by

`tests/test_aggregation.py` (23 tests), including: a single masked contribution
must not resemble its input; a partial cohort must raise rather than return; a
wrong secret must be detected, not silently wrong; masks must be round-bound; a
smaller cohort must widen the interval; and no per-subject field may survive
into the output.

## What would reverse this

A crypto dependency judged worth its audit cost would replace the symmetric
cohort secret with proper key agreement and add dropout recovery. That is a
strict improvement and this ADR would be superseded, not reversed.
