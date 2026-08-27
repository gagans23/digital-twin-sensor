# Context Capture Roadmap

The current sensor intentionally captures a narrow signal: active app, active window title, timestamp, dwell time, and inferred domain. That is enough to build an early Digital Twin Signature without crossing into surveillance.

To capture richer system context, add signals in layers. Each layer should be opt-in, visible in the UI, locally stored by default, and deletable.

## Layer 1: Safe Local Activity

- active app and window title
- dwell time
- domain classification
- app switching sequences
- idle detection
- manual annotations such as "this was client work" or "ignore this"

Status: active app/window collection exists. Idle detection and annotations are next.

## Layer 2: App-Specific Context

- browser history: URL domain, page title, visit timestamp
- IDE context: repo name, branch, changed files, active file path
- terminal context: command names, exit status, working directory
- calendar context: meeting title, participants, start/end time
- document context: file name, path, modified time

Privacy rule: store metadata first, not full contents. Full contents should require a separate per-connector toggle.

## Layer 3: Semantic Context

- local embeddings for titles/artifacts
- per-project topic clusters
- "why did this matter?" summaries
- recurring responsibilities inferred from repeated attention
- anomaly detection when attention shifts from baseline

Privacy rule: embeddings should stay local unless the user explicitly chooses a hosted model.

## Layer 4: Agent-Ready Context Packs

Inspired by Workfabric's ContextFabric framing, convert personal attention traces into reusable context packs:

- current priorities
- active projects
- frequently revisited artifacts
- neglected responsibilities
- recent decision trails
- handoff summaries for coding agents

These packs should be exportable to tools like Kiro, Codex, or GitLab issues without exporting the raw event database.

## Layer 5: Governed Deployment

Before any team or workplace use:

- visible collection indicator
- opt-in consent
- pause button
- retention policy
- deletion controls
- encryption at rest
- audit trail
- role-based access
- connector-specific scopes

## Recommended Next Build

1. Add collector status to the UI.
2. Add pause/resume controls.
3. Add retention/delete commands.
4. Add optional browser-history connector storing only domain and title.
5. Add optional git-repo connector for branch, diff stats, and changed files.
6. Add a local context-pack export command for Kiro/Codex prompts.

See `COLLECTION_DEPTH_AND_REDACTION.md` for the collection-depth model and masking policy.
