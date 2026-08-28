# UI Research And Direction

## References

Workfabric AI publicly positions itself as an enterprise simulation company building living digital twins of accounts, teams, products, and personas. Its ContextFabric platform is described as a layer that senses across apps, synthesizes operational context, and feeds that context to agent harnesses.

The Cognizant partnership announcement frames deployment around context engineering: capture enterprise knowledge, manage governance/privacy/security, build retrieval and synthesis pipelines, package reusable context packs, and create context blueprints for agentic use cases.

The X-SYNTH paper gives the product logic for this prototype: collect structured interaction records, maintain a Digital Twin Signature, route queries through attention filters, then rank evidence by multiplying attention importance with content relevance.

## What This UI Does Differently

Workfabric's public site is strong at category creation: context, simulation, living twins, governed agent grounding. For a personal sensor, the UI needs more operational trust.

This dashboard is therefore built around five plain questions:

1. What has been collected?
2. What did the system infer from it?
3. Why did a piece of evidence surface?
4. What is not collected?
5. Where does the data live?

## Visual Direction

The UI avoids a pure enterprise landing-page feel. It uses:

- a data-console first screen instead of a marketing hero
- neutral light surfaces with teal, coral, violet, amber, and green signal colors
- compact cards for metrics and repeated evidence
- explicit source-to-evidence pipeline
- a privacy ledger beside the behavioral analysis

## Information Architecture

- Overview: fast answer to current collection state and attention distribution
- Activities: inferred working spheres, session returns, resume packs, and grouping explanations
- Context Graph: privacy-gated relationships among domains, apps, artifacts, tasks, time, and masked private signals
- Twin Signature: five-vector behavioral profile from the paper
- Evidence: query interface that exposes selected filters and ranked artifacts
- Events: raw ledger for auditability
- Privacy: captured/not-captured boundaries and local database path

## Next Product Improvements

- add deletion and retention controls directly in the Privacy tab
- add a menubar indicator for sensor-on/sensor-off state
- add local semantic embeddings for better content scoring
- add feedback buttons to tune filter selection
- add connector-level toggles for browser, IDE, calendar, and documents
- add encrypted local storage before any workplace deployment
