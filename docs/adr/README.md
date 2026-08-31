# Architecture decision records

One file per decision that would be expensive to reverse. Each records what was
decided, what drove it, which test holds it in place, and what evidence would
overturn it.

The format is deliberately short. An ADR that takes an afternoon to write does
not get written, and a decision whose reasoning lives only in someone's head is
exactly the failure mode this project exists to argue about.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-sensor-not-twin.md) | Call it a sensor; refuse to claim a faithful twin | Accepted |
| [0002](0002-attention-not-content.md) | Capture attention and sequence, not content | Accepted |
| [0003](0003-redact-before-storage.md) | Redact before the write, not on read | Accepted |
| [0004](0004-zero-runtime-dependencies.md) | Zero runtime dependencies | Accepted |
| [0005](0005-admission-gate-field-level.md) | Field-level admission gate on every export | Accepted |
| [0006](0006-deterministic-harness-is-the-gate.md) | The deterministic harness is the CI gate, not the agents | Accepted |
| [0007](0007-count-based-aggregation-floor.md) | Count-based k-anonymity floor in synthesis | Accepted |
| [0008](0008-invented-confidence-weights.md) | Ship the confidence formula labelled as an unvalidated prior | Accepted, pending validation |
| [0009](0009-connector-manifests-are-allowlists.md) | Connector manifests are allowlists, not parsers | Accepted |
| [0010](0010-encryption-optional-and-partial.md) | Encryption at rest is optional and deliberately partial | Accepted |
