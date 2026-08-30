# Under the Hood

How context is actually captured, how this system defines attention, and what joins
the layers together. Every number below is in the code, not in a slide.

---

## 1. Capture — what a sensor event is

The collector samples the macOS foreground window on an interval (`run --interval 15`).
It does not stream. It does not hook input. Each sample becomes one event:

```json
{
  "app": "Kiro",
  "title": "payments gateway retry logic",
  "artifact": "payments gateway retry logic",
  "domain": "coding",
  "action": "focus",
  "ts_start": "…", "ts_end": "…",
  "dwell_seconds": 240.0,
  "metadata": { "redaction_findings": {"email": 1}, "privacy": "no_keystrokes_no_screenshots_no_clipboard" }
}
```

Three things happen before that row reaches SQLite, in this order:

1. **Depth policy** decides what may be read at all. Depth 1 is app plus window title.
   Depth 2 adds browser tab title and domain — URL path, query and fragment are separate
   flags, off by default. Depth 3 adds redacted Accessibility labels for allowlisted apps only.
2. **Domain classification** maps app plus title to a work domain via `domain_rules`.
3. **Redaction** masks emails, Luhn-valid card numbers, SSNs, phone numbers, IPs, token
   shapes, URL paths and configured names — and records *what it found* in
   `redaction_findings`, so the masking itself is auditable.

Redaction runs **before the write**, not before the query. That ordering is the whole
difference between a governed sensor and a surveillance log with a filter on top.

---

## 2. Attention — how the system defines it

Attention is not "time on screen". Dwell alone rewards the window you left open while
you went to lunch. The system models attention as a **distribution with a shape**,
computed in `twin.py` as the Digital Twin Signature:

| Vector | What it measures | How |
| --- | --- | --- |
| `v_dom` | where attention goes | dwell distribution across work domains |
| `v_rhythm` | when it goes there | hour-of-day histogram |
| `v_base` | what normal looks like | short window (5d) against long window (14d) |
| `v_resp` | how attention moves | domain-to-domain transition counts |
| `v_div` | how concentrated, how changed | Shannon entropy, plus KL divergence short vs long |

That last one earns its place. `KL(short ‖ long) > 0.2` means the recent week does not
look like the fortnight — the person's attention has shifted. The system uses that as a
trigger, not a statistic: retrieval automatically adds a `differential` filter when it fires.

### Attention filters

Retrieval (`query.py`) does not rank by relevance alone. It picks an **attention filter**
from cues in the question itself, then weights evidence by that filter:

| Filter | Cues in the question | What it surfaces |
| --- | --- | --- |
| `proportional` | *(default)* | what actually held attention |
| `inverse` | "missing", "ignored", "should have" | what was *neglected* — absence as signal |
| `differential` | "changed", "spike", "anomaly" | what shifted against baseline |
| `recurrent` | "again", "keeps coming back" | what was returned to repeatedly |
| `comparative` | "versus", "alternative" | what was evaluated against what |
| `sequential` | "then", "workflow", "order" | the order things were done in |
| `collective` | "team", "everyone" | cohort-level signal *(see the floor, §4)* |

Final rank is `attention_score × content_score`. Content alone finds the document; attention
decides whether the person was actually *working on it*. The `inverse` filter is the one
worth noticing — it treats what someone conspicuously did **not** look at as evidence,
which no document store can do.

---

## 3. The join layers

Six layers, each consuming the one below and discarding more than it keeps.

```mermaid
flowchart TB
  L1["<b>1 · Events</b><br/>redacted focus atoms"]
  L2["<b>2 · Signature</b><br/>5 attention vectors"]
  L3["<b>3 · Context graph</b><br/>typed nodes + edges"]
  L4["<b>4 · Working spheres</b><br/>temporal clustering"]
  L5["<b>5 · Admission gate</b><br/>purpose, sensitivity, freshness"]
  L6["<b>6 · Synthesis</b><br/>cross-subject, floor-gated"]
  L1 --> L2 --> L3 --> L4 --> L5 --> L6
  L4 -.->|scored against| L2
  L5 -.->|measured by| H["<b>Harness</b><br/>recall · noise · leaks"]
```

**Layer 3 — the graph** types everything: `domain`, `app`, `artifact`, `task`, `time`.
Edges carry dwell and event counts. Node score is
`dwell + events×5 + type_priority×120`, so a node earns its place by sustained
attention rather than by appearing once.

**Layer 4 — working spheres** is where interrupted work gets reconnected. Each incoming
event is scored against every open sphere and joins the best match above threshold:

| Signal | Weight |
| --- | --- |
| same normalised artifact | **0.46** |
| token overlap (Jaccard × 0.72) | up to **0.48** |
| same domain | 0.18 |
| same inferred task | 0.13 |
| same app | 0.12 |
| continuing the previous sphere within the session gap | 0.16 |
| ≥ 2 shared tokens | 0.08 |

Artifact identity and token overlap dominate deliberately. Same app and same domain are
weak evidence — a browser is a browser. Returning to *the same thing* is strong evidence,
and it is what lets the system say "you were interrupted here, three times" rather than
"you used Chrome for four hours".

**Layer 5 — the admission gate** is the only exit. Purpose must be declared, sensitivity
decides keep/mask/deny, freshness drops stale evidence and notes the gap, and the export
is re-redacted as defence in depth. Every pack carries what was withheld and why.

---

## 4. Synthesis — the layer above one machine

`synthesis.py` folds gated working spheres from many subjects into themes. It reads
**no raw events** and takes only opaque subject keys, and it enforces an aggregation
floor before anything is emitted:

```
a theme is emitted only when N distinct subjects independently support it
```

Below the floor, the theme is withheld **and counted**, so an operator sees that
suppression happened rather than quietly receiving a thinner answer. Confidence is
`0.65 × breadth + 0.35 × depth` — breadth is corroboration across people, depth is
volume. Weighting breadth higher is what stops one prolific person from manufacturing
a theme on their own; there is a test for exactly that.

> **Where that equation comes from: me.** The 0.65/0.35 split is a hand-chosen prior,
> not a result from any paper, and it has not been fitted against labelled data —
> because no labelled data exists yet. Only the *direction* is defensible (breadth
> above depth, and there is a test for it). The magnitudes are a placeholder awaiting
> calibration and should not be cited as a finding. The aggregation floor underneath
> is different: count-based k-anonymity is standard practice ([Sweeney,
> 2002](https://dataprivacylab.org/dataprivacy/projects/kanonymity/kanonymity.pdf)) —
> though a count floor is a floor, not a proof, and it does not defend against
> differencing across repeated queries.

This is the layer that makes anything above a single team defensible. It is also the
layer that must exist *before* deployment widens, not after — an aggregation floor is
cheap at ten endpoints and impossible to retrofit at ten thousand.

---

## 5. The harness

Unit tests prove a function returns what it was told to return. They cannot tell you
whether the context handed to an agent is good — relevant enough to be useful, tight
enough to be safe.

`harness.py` runs a golden set end to end and scores it:

| Metric | Meaning |
| --- | --- |
| **recall** | did the pack surface what the scenario says it must? |
| **noise ratio** | how much surfaced material was not expected? |
| **leaks** | did a canary reach an export? *hard failure, any count* |
| **evidence age** | how stale was the newest supporting evidence? |
| **pack size** | how much is being sent? |
| **gate counts** | allow / mask / deny decisions taken |

```bash
digital-twin-sensor harness                    # markdown report
digital-twin-sensor harness --format json      # machine-readable
digital-twin-sensor harness --fail-under 0.8   # tighten the recall floor
```

Non-zero exit on any leak or a recall miss, and it runs in CI, so a context regression
breaks the build exactly like a failing test.

> **It earned its keep immediately.** On its first run the harness failed
> `stale_evidence`: events 60 days old were being exported inside a 3-day window.
> The `days` argument was threaded through the builders as *metadata* and enforced only
> by `EventStore.fetch_window`. Any caller passing events directly — a batch job, a
> future control plane, a test — got stale evidence stamped with a fresh window.
> Fixed in `store.filter_window`, enforced in all three builders, regression test in
> `tests/test_harness.py`. Twenty-two unit tests had not found it in months.

---

## 5b. The deep harness — where determinism runs out

The harness above is deterministic, dependency-free and fast, and it stays the CI gate
for exactly those reasons: a build must not depend on a model API being reachable or on
a judge that gives a different answer twice.

But a regex canary can only prove that a *known string* did not escape. It cannot answer
the questions that actually decide whether this system is good:

- could a person resume this work from this pack, or is it merely tidy?
- what can be **inferred** about someone from a pack that leaked no literal PII?
- do synthesis themes describe real work, or token soup that reads like English?
- what is the golden set failing to test?

Those are judgements. `deep_harness.py` makes them with a planner and four sub-agents,
each with an isolated context window, running over the real pipeline:

| Sub-agent | Question it owns |
| --- | --- |
| `resumability-judge` | given only this pack, what would I do next, and what would I get wrong? |
| `leakage-adversary` | red team — infer employer, client, role, hours, personal life from a pack that passed the canaries |
| `synthesis-critic` | are themes actionable, and does the floor hold as supporters approach it? |
| `gap-analyst` | which untested scenario is most likely to fail *silently* in production? |

Context quarantine matters here. The adversary must not be softened by having read the
relevance judge's praise, which is why these are sub-agents with separate windows rather
than sections of one prompt.

```bash
pip install -e ".[deep-eval]"     # optional extra, Python >=3.11
export ANTHROPIC_API_KEY=...
digital-twin-sensor deep-harness
```

**Data boundary.** It runs against synthetic fixtures from `harness/scenarios.json`. It
does not read the local event store, because sending real captured attention to a model
API is the exact thing this product exists to avoid. The extra is developer-time only —
`dependencies = []` in `pyproject.toml` is deliberate and stays that way. A privacy tool
whose dependency tree a security team cannot read end to end is not a privacy tool.

---

## 5c. Encryption at rest

"Local-first" and "plaintext SQLite on disk" in one README is a contradiction, and it
is the first one a security review finds. The threat model here is a laptop at rest:
lost, stolen, backed up somewhere unexpected, or readable by any process running as
the same user. Redaction reduces what is *in* the file. It does not protect the file.

```bash
pip install -e ".[encrypted]"
digital-twin-sensor encrypt-store            # enable and migrate in place
digital-twin-sensor encrypt-store --status   # report without changing anything
```

**What is encrypted:** `title`, `artifact` and `metadata` — the three columns that
carry meaning. AES-256-GCM via `cryptography`, a vetted implementation of a standard
AEAD. Nothing here invents a primitive.

**What is not, and why it matters:** `ts_start`, `ts_end`, `dwell_seconds`, `domain`,
`app` and `subject_id` stay readable, because the store queries and sorts on them. So
an attacker holding the file still learns your working rhythm, your app mix and your
domain distribution. That is real signal, and calling this "encrypted at rest" without
saying so would be the kind of half-claim this project exists to avoid. Whole-database
encryption (SQLCipher) is the answer, and it needs a C extension this project does not
currently take. There is a test asserting the boundary so it cannot be quietly forgotten.

**Keys** live in the OS keychain where one is available. Failing that they go to a
0600 file beside the database, which is weaker — a process running as you can read it —
and the CLI says so out loud rather than degrading quietly.

**Migration is resumable.** Rows written before encryption decrypt to themselves, so a
half-migrated store stays readable and an interrupted migration can simply be re-run.
Encryption is idempotent in both directions for the same reason.

---

## 6. Known gaps

Honest list. These are the things that stand between this prototype and an enterprise
deployment, roughly in the order they would bite.

| Gap | Why it matters | Status |
| --- | --- | --- |
| **Store encryption is field-level, not whole-database** | timing, domain and app columns stay readable so the store can query them — an attacker with the file still learns rhythm and app mix. SQLCipher is the real answer | 🟡 partial |
| **Redaction is regex-only** | 120 lines catch patterns, not unlisted human names; needs NER | 🟡 partial |
| **No event-schema versioning** | a field rename orphans existing local history | ⬜ designed |
| **Retrieval is lexical** | token overlap misses synonymy; needs embeddings + a learned router | ⬜ designed |
| **No feedback capture** | H1–H5 stay untestable without labelled outcomes | ⬜ designed |
| **Sphere weights are hand-tuned** | the seven weights above are judgement, not fitted | 🟡 partial |
| **Synthesis floor is count-based** | k-anonymity only; no differential privacy, no defence against differencing across repeated queries | 🟡 partial |
| **Confidence weights are unvalidated** | 0.65/0.35 is a hand-chosen prior, never fitted — direction defensible, magnitude is a placeholder | ⬜ designed |
| **Deep-harness judgements are non-deterministic** | an LLM judge is a smoke alarm, not a proof; it informs review, it does not gate CI | 🟡 partial |
| **No pack provenance signature** | a receiving agent cannot verify a pack was gated | ⬜ designed |
| **No control plane** | enrolment, policy distribution, audit log all unbuilt | ⬜ designed |
| **macOS only** | Windows and Linux collectors unwritten | ⬜ designed |

The first four are what a security review would open with. The synthesis floor is the one
that decides whether tier 3 and above are honest — count-based k-anonymity is a real floor
but it is not a proof, and aggregate queries can still leak across repeated runs.
