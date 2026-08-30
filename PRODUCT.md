# Product Plan

**Decisions taken:** enterprise team pilot as the wedge, open core as the model, thin
control plane before the first design-partner conversation.

Everything below follows from those three. Where a choice is still open it is marked
**OPEN**, and where something is deliberately not being built it says so — a plan that
only lists work is a wish list.

---

## 1. What is being sold, and to whom

**Buyer:** the person accountable for an operations function in a regulated firm —
head of trade finance operations, head of financial crime ops, head of reconciliation.
Not the CIO, and not the innovation team. The buyer must feel the pain of losing the
forty people directly.

**The pain, stated in their words:** *"Half of what makes this function work is in
about forty heads. Two of them retire this year. My AI programme reads our documents,
which is the part that was already written down."*

**What they buy:** a governed way to see how the work is actually done — and to hand
that to agents — without deploying surveillance on their own staff, which is the thing
that would end their career.

**Why now:** they have already bought the model layer. It underperformed against the
slide, and they are looking for the reason. This names the reason.

### The wedge function

Start with **trade finance document checking on the UAE–India corridor**, one of the busiest documentary trade routes in the world and, since a comprehensive economic partnership agreement came into force in 2022, one where origin documentation carries real tariff consequence. It is the sharpest instance of the
argument and it is a function Gagan can speak to credibly:

- the rules are fully codified (UCP 600), so rule automation is already deployed
- 60–75% of first presentations come back discrepant, so the automation produces a
  word that is not a decision three times in four
- everything after that word — will this issuing bank refuse, will this applicant
  waive, is it faster to have the beneficiary re-present — is undocumented judgement
- under a preferential trade agreement the certificate of origin determines duty treatment, so an origin discrepancy is a customs exposure rather than a clerical one
- the value is measurable in days of working capital, not in "productivity"

A pilot that shows resume-time and discrepancy-handling improvement in that function
is a reference the rest of the bank understands.

> **Boundary on all public material.** Examples in the writing, the case study and this plan are drawn
> from public rulebooks, published trade agreements and general market structure. Nothing describes any
> employer's systems, clients or live problems, and nothing here depends on non-public information.

---

## 2. The open / commercial line

The line is drawn where trust demands openness and where scale demands operation.

| Layer | Licence | Rationale |
| --- | --- | --- |
| Endpoint collector, redaction, store, graph, spheres, admission gate | **MIT, public** | Nobody installs a closed-source attention sensor. The readable collector *is* the sale. |
| Deterministic harness, golden set | **MIT, public** | The method is the thought leadership. Giving it away is the point. |
| Deep-agent judgement harness | **MIT, public** | Same. |
| Control plane: enrolment, policy distribution, audit log, pack registry | **Commercial** | Operating a fleet is the work firms will pay to not do. |
| Multi-tenant synthesis, cohort floors, admin console | **Commercial** | Only has value above one team. |
| Signed installers, MDM profiles, support, SLA | **Commercial** | Deployment at scale. |

**The rule that keeps this honest:** anything that determines *what is collected* or
*what leaves the machine* stays open. Anything that operates a fleet is commercial. A
buyer's security team must be able to read every line that touches their staff's data,
without a licence, without an NDA.

---

## 3. Architecture invariants

Four properties that must hold at every commit. If a feature cannot be built without
breaking one, the feature is wrong.

1. **The control plane never receives raw events.** Enforced by the sync schema
   rejecting unknown fields — not by policy, not by a code review convention.
2. **The endpoint is fully useful offline.** An endpoint that degrades when
   disconnected gets uninstalled by exactly the people whose knowledge you need.
3. **Every sync is signed and logged.** Both sides can prove what crossed, and when.
4. **Aggregation floors are enforced server-side as well as client-side.** A
   compromised or modified endpoint must not be able to lower the floor.

---

## 4. The build, step by step

Roughly 6–8 focused weeks. Each milestone has a single acceptance test, because a
milestone without one is a vibe.

### M1 · Multi-subject foundations *(week 1–2)*

The current code assumes one subject on one machine. This is the prerequisite nobody
sees and everything depends on.

- Event-schema versioning and forward migration *(closes known gap #3)*
- Stable subject and device identity, with the opaque-key boundary already in
  `synthesis.py` extended through the store
- **Signed pack provenance** — a receiving agent can verify a pack came through a gate
  and was not assembled by hand *(closes known gap: no provenance signature)*
- Sync payload schema, with strict rejection of unknown fields

**Acceptance:** a pack can be verified by a third party with only the public key, and
a payload carrying a raw event field is rejected by schema, not by review.

### M2 · Enrolment and policy distribution *(week 2–3)*

- Device registers, receives a signed policy bundle, reports a heartbeat
- Policy version pinned per device and visible on the endpoint
- Local override still possible, and *logged* — an operator who cannot pause is a
  surveillance target, not a user

**Acceptance:** change a capture-depth policy centrally; twenty simulated endpoints
converge and each shows the new policy locally within one heartbeat interval.

### M3 · Summary sync and audit log *(week 3–4)*

- The only data path off the endpoint: gated packs plus health, signed
- Append-only audit log: what synced, when, under which policy version, approved by whom
- Retention and deletion propagated from the control plane

**Acceptance:** an auditor can reconstruct, from the log alone, every piece of context
that ever left a given endpoint. A deletion request removes it everywhere and the log
proves it.

### M4 · Multi-tenant synthesis and admin console *(week 4–6)*

- `synthesize_collective` running server-side across enrolled devices
- Cohort floors enforced server-side; withheld counts surfaced to the admin
- Console: fleet health, policy state, connector inventory, themes, suppression counts

**Acceptance:** with twenty endpoints and a floor of five, a theme supported by four
subjects is invisible to the admin *and* the admin can see that something was withheld.

### M5 · Pilot hardening *(week 6–8)*

- Signed macOS `.pkg`, LaunchAgent, MDM profile for Accessibility
- Employee-facing consent and transparency view — not the admin console
- Operations runbook, incident path, support commitment

**Acceptance:** a member of staff can, unprompted, see everything the system holds
about them, pause it, and delete it. Without asking IT.

### Not being built yet, deliberately

Windows and Linux collectors. Embeddings and the learned retrieval router. Feedback
capture and the H1–H5 evaluation. SQLCipher whole-database encryption. Differential
privacy on aggregates. Connector marketplace.

Each is real work and none of it is on the path to learning whether a firm will deploy
this at all. They wait for what the pilot teaches.

---

## 5. The pilot

**Shape:** one function, 20–50 endpoints, 8–12 weeks, paid but priced as a pilot.
Paid matters — a free pilot has no internal owner and dies at the first works-council
question.

**What the partner commits:** a named operations sponsor, access to the function's
actual questions for the golden set, and a works-council or employee-representative
conversation *before* deployment rather than after.

**What we commit:** deployment, the golden set built from their questions, weekly
measurement, and full deletion at exit.

### Success metrics

| Metric | Why it is the right one |
| --- | --- |
| Task-resume time after interruption | The mechanism this product actually improves |
| Context precision, judged by their experts | Whether the context is *right*, not just present |
| Leakage incidents | Must be zero. Any non-zero result ends the pilot |
| Share of packs approved for export | Whether the gate is usable or merely safe |
| Endpoint uninstall rate | The honest adoption signal — nobody uninstalls a tool they trust |

That last one is the metric to watch hardest. If staff quietly remove it, nothing else
on the list matters.

---

## 6. What kills this

Ranked by probability, not by how uncomfortable they are to write down.

1. **Employee consent.** In a European or Gulf regulated firm, a works council or
   staff-representative body can stop this in one meeting. Mitigation is product, not
   messaging: the employee-facing transparency view ships in M5 *before* any pilot, and
   the pause and purge controls stay local and unlogged-to-admin.
2. **It reads as surveillance regardless of the gates.** The honest test: would you
   install it on your own machine, knowing your manager has the console? If the answer
   is hesitant, the product is not finished.
3. **The value does not show up.** If task-resume time does not move in a real
   function, the thesis is wrong at the level of the essay, not just the product. Better
   to learn that in week ten of a pilot than in year two of a company.
4. **Accessibility permission at scale.** MDM makes this tractable on managed Macs and
   nearly impossible on unmanaged ones. Constrains the buyer to firms with real MDM.
5. **A single leak ends it.** One reconstructed identity from a synthesised theme and
   the product is finished, regardless of how good the rest is. This is why the floor is
   enforced twice and why leakage is a hard-fail metric rather than a tracked one.

---

## 7. Open questions

**OPEN — naming.** The endpoint is Digital Twin Sensor. The commercial layer needs its
own name; "digital twin" carries baggage the research itself warns about
([funhouse mirrors](https://arxiv.org/abs/2509.19088)), and the honest framing has always
been *context*, not *twin*.

**OPEN — entity and licence.** Open-core needs a decision on which entity holds the
commercial layer, and whether the OSS licence stays MIT or moves to something with a
network clause.

**OPEN — first conversation.** Which two or three firms, and whether the first
conversation happens after M3 (enough to demo sync and audit) or after M5 (enough to
actually run).
