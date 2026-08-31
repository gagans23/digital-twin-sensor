# Threat model

This tool watches how someone works. That is a sentence worth being uncomfortable
about, and the mitigations only mean something if the threats are written down
next to them.

Scope: the local sensor, the local store, and anything that leaves the machine as
a context pack. The optional deep-eval layer is developer-time only and is
covered where it touches data.

## What is being protected

| Asset | Why it matters | Where it lives |
| --- | --- | --- |
| Attention trace | Reveals what someone worked on, when, and in what order | SQLite, local |
| Artefact and window titles | Often the most sensitive strings on the machine — client names, deal codes, ticket subjects | SQLite, redacted before write |
| Context packs | The only artefact designed to leave the machine | Export target |
| Aggregated themes | Can re-identify a small team's work if the floor fails | Synthesis output |
| The subject's willingness to run it at all | Everything above depends on this | Not technical |

That last row is not decoration. A capture tool that is switched off collects
nothing, so trust is a security control here, not a nice-to-have.

## Adversaries, and what each one gets

**1. Thief with the disk.** Reads `work.sqlite` directly. Without the `encrypted`
extra and explicit encryption enablement they get redacted titles and full timing metadata. When enabled, event titles,
artefacts, metadata, learning-card text and feedback notes are AES-256-GCM ciphertext, and they still get `ts_start`,
`ts_end`, `dwell_seconds`, `domain`, `app` and `subject_id` — enough to
reconstruct *when* someone worked, in which application, and for how long.
That is a real disclosure and ADR 0010 explains why the boundary sits there.
Anyone who needs the timing protected should use full-disk encryption; this tool
does not replace it.

**2. Curious process on the same machine.** Any process running as the same user
can read the database file and, if the keyfile fallback is in use, the key beside
it. The OS keyring is the default for exactly this reason, and the keyfile path
warns loudly when it is taken. This tool does not defend against an attacker who
is already running as you — nothing at this layer can.

**3. The receiving agent.** The most likely leak in normal operation. An agent
handed a context pack sees only what the admission gate allowed, and every denial
travels with the pack. This is the boundary the harness canaries and the property
tests in `tests/test_fuzz_leak_gate.py` exist to hold. Two evasions have been
found and fixed here so far; both were found by generated inputs, not by the
golden set, which is the honest argument for keeping the fuzzing.

**4. The subject's own employer.** The uncomfortable one. A tool that observes an
operator can be turned into a productivity surveillance system by whoever
controls its configuration. The mitigations are structural rather than
cryptographic: collection depth is visible in the dashboard to the person being
observed, the gate's decisions and exclusions are inspectable by them, pause and
purge are local controls, and the aggregation floor suppresses small themes but does not
guarantee anonymity. None of this survives a determined employer with
root on the machine, and the documentation should not pretend otherwise.

**5. The re-identifier.** Receives aggregated themes and tries to attribute them
to a person. Countered by the count-based k-anonymity floor (ADR 0007): themes
below `min_subjects` have their label and support count withheld. `subject_key` is an unsalted
`sha256[:12]` pseudonym, vulnerable to guessing when subject identifiers are known. A determined adversary
with side knowledge of team composition can still narrow a theme; k-anonymity is
a floor, not a guarantee, and a differential-privacy layer would be the upgrade.

**6. The malicious connector manifest.** A manifest is an allowlist, so a hostile
one can only widen collection within declared, validated fields — and validation
rejects unknown sources, missing descriptions, token fields without an allowlist,
and patterns without a capture group. Manifests are code review surface, and
should be treated as such.

## What is out of scope, deliberately

- Keystrokes and clipboard are not collected. Opt-in OCR uses transient screenshots;
  cleanup after crashes needs further testing, so screen capture is not out of scope.
- Network exfiltration by other software on the machine.
- An attacker with root, or with the user's login session.
- Anything the OS itself already logs.

## Assumptions redaction makes

Redaction is pattern matching, and pattern matching has a recall below one. It
runs before storage (ADR 0003); false positives destroy signal and false negatives can leak it,
and the patterns cover emails, phone numbers, national IDs, Luhn-valid card
numbers, IPs, URLs beyond host, and prefixed secrets. It does **not** understand
semantics: a client name that is not in `name_terms_to_mask` and looks like an
ordinary word will survive, and a deal codename is indistinguishable from a
project codename. Sensitive-title heuristics and per-sphere gate modes exist
because of this gap, not in spite of it.

The property tests exist to keep that recall honest under inputs nobody thought
of. They have found two leaks so far, which is the best available evidence that
the golden set alone was not enough.

## Known gaps

- No formal privacy guarantee on aggregates; k-anonymity floor only.
- Timing metadata is unencrypted by design and is genuinely disclosive.
- The keyfile fallback is weaker than the keyring and is only warned about.
- Redaction recall is unmeasured against real workstation titles, because that
  corpus does not exist yet and manufacturing one would be worse than admitting
  the gap.
