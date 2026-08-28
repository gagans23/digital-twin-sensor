# Related Context Papers And Product Ideas

Research pass date: 2026-08-28

This project should not treat a digital twin as a static profile vector. The stronger product direction is a living context graph with privacy gates: observed activity becomes evidence, evidence becomes task/project structure, and only purpose-appropriate context is admitted into agent prompts or exports.

## Core Thesis

The current sensor already captures Depth 1 attention metadata and derives a privacy-gated context graph. The next leap is to infer "working spheres" and "task models" from those traces, then expose them as explainable context packs for Kiro, Codex, GitLab issues, and future agents.

In product terms:

```text
Raw local events -> Redaction -> Seen index -> Context graph -> Working spheres -> Task models -> Context packs
```

Every step should preserve provenance and show why a fact was admitted, masked, generalized, or withheld.

## Most Actionable Papers

### X-SYNTH: Digital Twin Signature

Source: https://arxiv.org/pdf/2605.15505

Useful concept: maintain a Digital Twin Signature made from domain preference, rhythm, baseline, response deviation, and attention diversity. Route queries through attention filters instead of using query similarity alone.

Product implementation:

- keep the current DTS radar view
- add a "signature drift" panel showing what changed from the user's baseline
- use the DTS to pick retrieval strategies, not only to display analytics

### Inducing Task Models from Computer-Use Traces

Source: https://arxiv.org/abs/2608.20319

Useful concept: infer latent tasks from raw computer-use traces, including interleaved goals, hierarchical objectives, and procedure/control-flow structure.

Product implementation:

- build `working_spheres.py` to cluster events by app, domain, artifact, sequence, and return frequency
- add `task_model.py` to infer objective nodes such as "research Kiro", "edit digital twin UI", or "prepare GitLab handoff"
- display non-contiguous work as one task when the user returns to the same sphere over time
- show a procedure trail: opened docs -> edited code -> ran tests -> checked dashboard

### Stuff I've Seen

Source: https://www.microsoft.com/en-us/research/publication/stuff-ive-seen-a-system-for-personal-information-retrieval-and-re-use/

Useful concept: personal search should support re-finding information the user has already seen, across emails, web pages, documents, appointments, and files.

Product implementation:

- create a metadata-only "seen index"
- store source type, title, app, domain, timestamp, local artifact pointer, and graph node id
- do not store page/body text by default
- add a "Find what I saw" UI search that ranks by attention, recency, repetition, and graph proximity

### Activity-Based Computing

Source: https://interruptions.net/literature/Bardram-CHI06-p211-bardram.pdf

Useful concept: the activity, not the app or file, should be the main unit of computing. Activities can be started, suspended, resumed, shared, and moved across devices.

Product implementation:

- add first-class "activity" objects above events
- let users rename, merge, split, pin, or ignore inferred activities
- make the UI start with active/suspended activities instead of only app charts
- export an activity as a context pack

### Disruption And Recovery Of Computing Tasks

Source: https://erichorvitz.com/CHI_2007_Iqbal_Horvitz.pdf

Useful concept: interruptions create chains of diversion and context loss. Recovery tools should give cues that help users return to suspended tasks quickly.

Product implementation:

- detect "return after interruption" from app-switch sequences and gaps
- create a resume card with last artifacts, last command/test, last evidence item, and next-action guess
- show "diversion chain" in the UI: original task -> notification/app switch -> side task -> return
- add a local notification only when the user asks for recovery cues

### Privacy As Contextual Integrity

Source: https://digitalcommons.law.uw.edu/wlr/vol79/iss1/10/

Useful concept: privacy is not just secrecy or consent. Privacy depends on whether information flows are appropriate for the current context, recipient, purpose, and transmission rule.

Product implementation:

- add a query-time memory admission gate
- require each export/request to declare purpose: self-reflection, coding context, issue handoff, agent prompt, analytics
- gate by source, sensitivity, age, relationship, and recipient
- show "why admitted" and "why withheld" beside every context pack

### GraphRAG, LightRAG, HippoRAG, And MemoRAG

Sources:

- https://arxiv.org/abs/2404.16130
- https://arxiv.org/abs/2410.05779
- https://arxiv.org/abs/2405.14831
- https://arxiv.org/abs/2409.05591

Useful concept: vector similarity alone is weak for global sensemaking. Graphs, graph communities, global memory, and graph-propagation retrieval help answer questions like "what themes dominated my week?" or "what is connected to this project?"

Product implementation:

- cluster the context graph into project/task communities
- create short community summaries with evidence links
- implement graph-proximity scoring using seeded nodes plus edge weights
- use Personalized PageRank-style retrieval for associative recall

### A-Mem, ACE, Generative Agents, And MemGPT

Sources:

- https://arxiv.org/html/2502.12110v1
- https://arxiv.org/abs/2510.04618
- https://arxiv.org/abs/2304.03442
- https://arxiv.org/abs/2310.08560

Useful concept: useful memory evolves. It is not just append-only logs. Strong systems consolidate observations into structured notes, reflections, plans, playbooks, and tiered memory.

Product implementation:

- add nightly "context cards" for active activities and projects
- each card should have summary, evidence links, open questions, likely next actions, sensitivity label, and expiry
- support memory evolution: new events can update an old card instead of creating duplicates
- separate memory tiers: hot session context, recent working memory, long-term graph memory, archived/expired memory

### Trustworthy Memory Search For Personal AI Agents

Source: https://arxiv.org/html/2606.06054v1

Useful concept: memory retrieval is a trust boundary. Semantically similar memories can still be inappropriate, causing cross-domain leakage, unsafe personalization, or tool-call drift.

Product implementation:

- never inject raw top-k memory into an agent prompt
- run retrieval through an admission decision: allow, summarize, generalize, mask, or deny
- include an audit trail for every admitted memory
- add tests proving sensitive entities do not cross context boundaries

### Knowledge Graphs In The Digital Twin

Source: https://arxiv.org/abs/2406.09042

Useful concept: knowledge graphs help digital twins integrate heterogeneous data sources and support automated adaptation as the twin changes.

Product implementation:

- keep the context graph as the product spine
- treat connectors as source adapters into one semantic graph
- store typed relationships, not just text blobs
- show graph maintenance health: stale nodes, disconnected nodes, sensitive nodes, high-signal nodes

## Product Concepts To Implement

### 1. Working Sphere Detector

What it does: groups events into the real units of work the user experiences, such as "digital twin sensor", "Kiro setup", or "research context papers".

Inputs:

- event sequence
- app name
- redacted window title
- inferred domain
- artifact labels
- return frequency
- dwell time

Output:

- working sphere id
- label suggestion
- confidence
- active/suspended status
- associated artifacts and graph nodes

UI:

- new "Activities" tab
- active sphere, suspended spheres, recent returns, top artifacts
- merge/split/rename/ignore controls

### 2. Task Model Lite

What it does: turns a working sphere into an auditable task model: objective, subgoals, steps, blockers, and evidence.

Start simple:

- objective inferred from repeated titles/domains
- steps from event order and command/test events when available
- blockers from error-like titles, repeated failed commands, or user annotations

UI:

- task tree beside the graph
- procedure timeline
- "confidence is low because..." explanation

### 3. Resume Pack

What it does: when the user returns to a suspended sphere, the product shows enough context to restart quickly.

Pack contents:

- last active artifact
- last 5 meaningful events
- last query or test command, when available
- open decisions
- next-action guess
- privacy gate summary

### 4. Seen Index

What it does: supports "what was that thing I saw?" without indexing private content by default.

Schema idea:

```text
seen_items(id, source_type, source_ref, title_redacted, domain, app, first_seen_at, last_seen_at, seen_count, graph_node_id, sensitivity)
```

### 5. Memory Admission Gate

What it does: decides what context can be used for each query/export.

Decision labels:

- allow
- summarize
- generalize
- mask
- deny

Inputs:

- requested purpose
- candidate memory
- sensitivity
- source connector
- recipient/tool
- age
- user policy

### 6. Evolving Context Cards

What it does: consolidates repeated observations into living notes.

Card fields:

- title
- summary
- evidence ids
- related spheres
- open questions
- likely next action
- sensitivity label
- expiration/retention date

### 7. Graph Community Summaries

What it does: turns graph clusters into readable project summaries.

Good questions it should answer:

- what dominated my week?
- what projects are drifting?
- what artifact keeps coming back?
- which context is stale?
- what should I export to Kiro?

### 8. Context Pack Export

What it does: packages the safe subset of context for another tool.

Targets:

- Kiro steering/spec prompts
- Codex task handoff
- GitLab issue/update
- local markdown report

Export should include:

- purpose
- selected working sphere
- summary
- evidence links
- withheld/masked counts
- retention note

## Recommended Build Order

1. Working sphere detector and Activities tab. Status: implemented at Depth 1.
2. Seen index table and metadata-only search.
3. Stronger resume packs from activity switches.
4. Memory admission gate for queries and exports.
5. Context pack export command for Kiro/Codex/GitLab.
6. Nightly evolving context cards.
7. Graph community summaries and graph-proximity retrieval.
8. Optional browser, Git, IDE, terminal, and calendar connectors.
9. Retention/delete UI across events, seen items, activities, and cards.
10. Stronger local security: encryption at rest and visible menubar indicator.

## What Not To Build Yet

- screenshots by default
- keystroke capture
- clipboard capture
- full email or document body indexing
- automatic cloud sync of raw events
- team/workplace monitoring features

Those can create power, but they also create surveillance risk. The product should win on context quality, user control, provenance, and purpose-specific memory admission.
