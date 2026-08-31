# Research And Evaluation

This project is inspired by X-SYNTH and related context engineering, agent memory, and digital twin papers. The current prototype should be described as a privacy-gated attention-context system, not as a faithful copy of a person.

## Research Thesis

```text
Observed digital attention can improve agent handoff when transformed into privacy-gated context graphs, working spheres, and summary-only context packs.
```

## What The Prototype Already Supports

- local continuous attention collection
- pre-storage redaction
- Digital Twin Signature vectors
- X-SYNTH-lite attention filters
- context graph over work evidence
- working sphere detection
- resume packs
- Memory Admission Gate
- Kiro/Codex/GitLab context-pack export
- local feedback labels for packs, spheres, and evidence
- evolving context cards over working spheres
- Depth 4 local OCR summaries for explicitly allowlisted opaque apps
- product doctor and watchdog
- pause/resume and retention controls
- research backlog in the dashboard

## Current Deviations From X-SYNTH

| Area | X-SYNTH | Current prototype |
| --- | --- | --- |
| Router | Learned Query x DTS modality router | Heuristic rule cues plus DTS weights |
| Feedback | Failure attribution across modality, retrieval, synthesis | Local pack/sphere/evidence labels; failure attribution metrics still need study protocol |
| Collective signal | Collective filters across enterprise traces | Single-user local traces only |
| Evaluation | TLR/FLR metrics | Needs task-resume and answer-quality evaluation |
| Causality | Attention used as contextual evidence | Current product should not claim causal proof |

## Proposed Study Design

Compare five conditions:

1. no context
2. query-only retrieval
3. raw top-k event retrieval
4. privacy-gated context pack
5. graph + working-sphere context pack

Measure:

- task-resume time
- context precision
- context recall by human judgment
- irrelevant evidence rate
- stale evidence rate
- privacy leakage rate
- context-pack size
- user trust calibration
- agent task outcome
- failure attribution

## Experiment Log Template

```text
date:
participant/device:
task:
target agent:
context condition:
time away from task:
time to resume:
agent outcome:
useful evidence count:
irrelevant evidence count:
privacy gate counts:
human usefulness rating:
failure attribution:
notes:
```

## Reasonable Product Ideas From 2024-2026 Papers

| Idea | Build status | Why it matters |
| --- | --- | --- |
| Evolving context cards | Implemented | Turns repeated observations into maintainable memory |
| Memory maintenance doctor | Partial | Detects stale, duplicate, or unsupported memories |
| Dynamic graph evolution | Next | Explains why relationships change over time |
| Feedback-labeled context packs | Partial | Creates train/evaluate data for routing policies |
| Local OCR summary gate | Implemented | Gives opaque apps richer context without storing image pixels |
| Offline policy rehearsal | Research | Tests context policies before live use |
| Trust calibration UI | Next | Prevents overclaiming and false confidence |
| Anti-overclaim benchmark | Research | Measures bias, distortion, and individuation |
| Event-bus simulator | Future | Enables reproducible digital-twin experiments |

See `../CONTEXT_RESEARCH_SYNTHESIS_2024_2026.md` for source-by-source notes.
