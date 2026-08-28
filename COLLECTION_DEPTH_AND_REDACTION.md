# Collection Depth And Redaction

The useful question is not "can we collect everything?" Technically, a local agent can observe a lot. The product question is "what is the least invasive signal that creates a useful digital twin?"

This project should use progressive collection depth. Each layer is opt-in, visible in the dashboard, masked before storage, and reversible.

## Depth 0: Health Only

Purpose: prove the service is alive.

Collect:

- timestamp
- collector status
- system state such as locked screen or screensaver

Store:

- no foreground content
- no app title
- no user text

Use for:

- uptime
- pause/resume state
- "sensor is running but cannot see active context"

## Depth 1: Attention Metadata

Purpose: build a behavioral attention map.

Collect:

- foreground app
- window title
- timestamp
- dwell time
- inferred domain
- app-switching sequence

Store:

- masked title
- no screenshots
- no keystrokes
- no clipboard
- no document body text

This is the current default.

Graph behavior:

- derive subject, domain, app, artifact, task, and time nodes from redacted events
- represent detected sensitive text as masked private-signal nodes, not raw entities
- exclude system-state events from the work-context graph by default
- expose gate counts for allowed, masked, generalized, and withheld graph elements

Working sphere behavior:

- cluster redacted focus events into inferred real activities
- reconnect interrupted work when artifacts, terms, apps, domains, or task labels repeat
- split continuous sessions when the same sphere returns after a long gap
- create resume packs with last artifact, recent path, next-action guess, and privacy-gate status
- exclude system-state events from activity inference by default

Context-pack behavior:

- select one working sphere automatically or by id
- pass fields through a Memory Admission Gate before export
- emit allowed, summarized, masked, and denied counts
- export Markdown or JSON without raw event rows, subject identity, event ids, full URLs, screenshots, keystrokes, clipboard, document bodies, or credentials

Pipeline:

```text
Sense -> Privacy Gate -> Context Graph -> Working Spheres -> Digital Twin Signature -> Evidence
```

## Depth 2: Work Surface Context

Purpose: understand what kind of work is happening without reading the work.

Optional connectors:

- browser: tab title, URL domain, sanitized URL, stripped URL path/query/fragment
- IDE: repo name, branch, active file path, changed-file list
- terminal: command name, working directory, exit code
- calendar: meeting title, time block, attendee count
- files: file name, extension, modified time

Default rule:

- store metadata only
- strip URL query strings and fragments
- mask usernames in file paths
- never store command arguments until explicitly enabled

Current browser status:

- Safari and Google Chrome active-tab metadata can be captured at Depth 2+
- URL paths and query strings remain off by default
- tab titles are passed through the same PII/name/card/secret redaction rules before storage

Enable the safe browser detail layer:

```bash
digital-twin-sensor configure --depth 2 --browser-tab-details on --browser-url-path off --browser-url-query off
```

## Opaque App Detail

Some apps, including players and embedded web views, may expose only the app name or generic window title. For those, the sensor cannot honestly know the in-app content from Depth 1 metadata.

Recommended escalation order:

1. manual labels: let the user rename the working sphere
2. Accessibility metadata: read visible labels/control names from a per-app allowlist
3. local OCR summary: capture a temporary window image, run local OCR, redact text, store only the summary, then discard the image
4. full screenshots: avoid unless there is a narrow, explicit need, encryption is enabled, and retention is short

Do not enable keystrokes, clipboard capture, microphone, raw screenshots, or cloud upload for opaque-app detail.

## Depth 3: Semantic Summaries

Purpose: create richer agent context packs.

Collect:

- local summaries of active documents
- local embeddings of titles/artifacts
- topic clusters
- decision trails
- repeated-work summaries

Default rule:

- summarize locally when possible
- store summary, not raw source text
- expose citations back to local artifacts
- allow per-artifact delete

## Depth 4: Full Content

Purpose: deep agent grounding.

Collect:

- document body text
- page text
- selected chat/email thread content
- code snippets

Default rule:

- off by default
- per-connector opt-in
- retention limits required
- encryption required
- export disabled unless user confirms

This layer is powerful, but it is where the product becomes privacy-sensitive. Do not turn it on casually.

## Redaction Policy

Redaction happens before SQLite storage.

Currently masked:

- emails
- credit-card-like numbers validated with Luhn
- US SSNs
- phone numbers
- IPv4 addresses
- common secret/API token shapes
- URL paths, query strings, and fragments
- configured names and usernames

Credit card handling uses a strict default: replace the full detected value with `[credit-card]`. Do not retain first six or last four unless there is a real operational need.

Name masking is configurable because blind name detection can create false positives and false confidence. Add names and aliases to:

```json
{
  "name_terms_to_mask": ["your-name", "your-alias", "client-name"]
}
```

## UI Requirements

The dashboard must always show:

- whether collection is active
- which local endpoint is being managed
- active policy and sync-readiness gates
- last sample age
- active collection depth
- what is captured
- what is not captured
- what redaction categories have fired
- the privacy-gated context graph
- inferred working spheres, session returns, and resume packs
- context-pack admission counts, denied fields, admitted evidence, and copyable Markdown
- graph minimization behavior such as excluded system-state samples
- where the local database lives

Fleet behavior:

- one local device is registered by default
- the Fleet tab shows collector/dashboard health, active policy, connectors, and portability status
- enterprise sync is local-only until a control plane is configured
- raw event upload is blocked by default

## Product Principle

Prefer:

- "I saw you spent 42 minutes in coding/research/planning"

Over:

- "I read every word you saw or typed"

The first creates useful context. The second creates surveillance risk.
