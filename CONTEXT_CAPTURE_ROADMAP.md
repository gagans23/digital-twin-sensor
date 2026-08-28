# Context Capture Roadmap

The current sensor intentionally captures a narrow signal: active app, active window title, timestamp, dwell time, and inferred domain. That is enough to build an early Digital Twin Signature without crossing into surveillance.

The current dashboard also derives a living context graph from that redacted event ledger. The graph connects subject, domain, app, artifact, task, and time nodes, then adds masked private-signal nodes when redaction fires. It now also infers working spheres: real activities reconstructed from shared artifacts, terms, apps, domains, dwell, and return patterns. Locked-screen and system-state samples stay available for collection health, but are excluded from the work-context graph and working-sphere detector by default.

To capture richer system context, add signals in layers. Each layer should be opt-in, visible in the UI, locally stored by default, and deletable.

## Layer 1: Safe Local Activity

- active app and window title
- dwell time
- domain classification
- app switching sequences
- idle detection
- manual annotations such as "this was client work" or "ignore this"

Status: active app/window collection exists. Idle detection and annotations are next.

Graph status: implemented for Depth 1. The graph is rebuilt from the current dashboard time window and does not persist a second copy of the event stream.

Working sphere status: implemented for Depth 1. The detector clusters redacted events into active, suspended, and dormant activities; builds recent-session timelines; records sphere-to-sphere transitions; and emits resume packs with last artifact, recent path, next-action guess, and privacy-gate status.

## Layer 2: App-Specific Context

- browser history: URL domain, page title, visit timestamp
- active browser tab: redacted tab title, URL domain, sanitized URL, path/query policy
- IDE context: repo name, branch, changed files, active file path
- terminal context: command names, exit status, working directory
- calendar context: meeting title, participants, start/end time
- document context: file name, path, modified time

Privacy rule: store metadata first, not full contents. Full contents should require a separate per-connector toggle.

Status: Safari and Google Chrome active-tab metadata are implemented at Depth 2+. Opaque app detail is not enabled yet; use manual labels first, then per-app Accessibility metadata, then local OCR summaries only with explicit opt-in.

## Layer 3: Semantic Context

- local embeddings for titles/artifacts
- per-project topic clusters
- graph-backed task and project clusters
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

1. Add pause/resume controls.
2. Add retention/delete commands.
3. Add optional browser-history connector storing only domain and title.
4. Add optional git-repo connector for branch, diff stats, and changed files.
5. Add task-model induction on top of working spheres.
6. Add graph-backed project/task community summaries.
7. Add a local context-pack export command for Kiro/Codex prompts.

See `COLLECTION_DEPTH_AND_REDACTION.md` for the collection-depth model and masking policy.
