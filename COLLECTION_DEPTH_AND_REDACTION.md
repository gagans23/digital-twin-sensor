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

Pipeline:

```text
Sense -> Privacy Gate -> Context Graph -> Digital Twin Signature -> Evidence
```

## Depth 2: Work Surface Context

Purpose: understand what kind of work is happening without reading the work.

Optional connectors:

- browser: domain, page title, stripped URL path
- IDE: repo name, branch, active file path, changed-file list
- terminal: command name, working directory, exit code
- calendar: meeting title, time block, attendee count
- files: file name, extension, modified time

Default rule:

- store metadata only
- strip URL query strings and fragments
- mask usernames in file paths
- never store command arguments until explicitly enabled

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
- last sample age
- active collection depth
- what is captured
- what is not captured
- what redaction categories have fired
- the privacy-gated context graph
- graph minimization behavior such as excluded system-state samples
- where the local database lives

## Product Principle

Prefer:

- "I saw you spent 42 minutes in coding/research/planning"

Over:

- "I read every word you saw or typed"

The first creates useful context. The second creates surveillance risk.
