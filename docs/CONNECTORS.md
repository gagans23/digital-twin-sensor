# Structured App Connectors v1

A connector turns what an application already displays into a small set of
declared, typed fields — so the sensor learns *what* you were working on rather
than only *that* you were in an app, and so the most invasive capture path is
reached as rarely as possible.

## Why manifests instead of code

Before this layer, each collector sanitised itself. That works, but the privacy
boundary for an app was spread across whichever function happened to handle it,
and supporting a new app meant writing code that could store anything.

A manifest inverts that:

```text
a field not declared in the manifest cannot be stored, whatever a source returns
```

The framework enforces the allowlist. Adding an app becomes a reviewable JSON
diff rather than a new code path, and a security reviewer can read
`connectors/manifests/*.json` and know the complete set of things that app can
contribute — without reading any Python.

## The depth model still governs everything

A manifest declares the minimum depth it needs and the ordered sources it may
read. It can never read a source the user has not enabled, and it can never
raise its own depth.

| Depth | Source | What it exposes |
| --- | --- | --- |
| 1 | `window_title` | what the app already puts in its title bar |
| 2 | `browser_tab` | tab title and domain — never path or query |
| 3 | `accessibility` | allowlisted, redacted UI labels |
| 4 | `ocr` | local OCR summary, only for allowlisted opaque apps |

**Cheaper sources win.** Fields are resolved in the manifest's declared source
order and the loop stops at the first source that answers. If Accessibility
returns a title, the OCR path is never invoked for that field — and the
dashboard reports it under *costlier sources not needed*.

That is the point of this release. OCR remains available as a fallback; the
connectors exist so it is needed less often.

## Shipped connectors

### `browser_page` — Safari, Chrome · depth 2

| Field | Store | Notes |
| --- | --- | --- |
| `page_title` | redacted | masked before storage |
| `domain` | domain | bare hostname; a path-like value is truncated to the host |
| `page_kind` | token | matched against a fixed list (docs, issue, pull request, …) |
| `heading` | redacted | top heading, only if depth 3 is also enabled |

Never declared, therefore never storable: URL path, query, fragment, cookies,
form values, page body, credentials.

### `media_player` — Ibo Pro Player · depth 3

| Field | Store | Notes |
| --- | --- | --- |
| `media_title` | redacted | from Accessibility labels, or an OCR summary if empty |
| `module` | redacted | module/lesson/chapter label when exposed |
| `playback_state` | token | playing, paused, buffering, stopped, live |
| `position` | redacted | timestamp as displayed |

Never declared: video frames, persisted screenshots, audio, full subtitle text,
account identifiers, stream URLs.

### `dev_workspace` — Kiro, Code, Cursor, Codex, Terminal · depth 1

| Field | Store | Notes |
| --- | --- | --- |
| `repo` | redacted | repository or workspace name, as the editor titles it |
| `branch` | redacted | branch name when the surface exposes one |
| `active_file` | redacted | file name only — never the path, never the contents |
| `dirty_files` | count | an integer, never a list of files |

**This connector never touches the filesystem and never runs `git`.** Everything
comes from what the editor already puts in its own window title. A tool that
opened your working tree to learn about your work would be the thing this
product exists to avoid.

Never declared: file contents, diff bodies, source code, commit messages, remote
URLs, credentials, env files.

## Provenance and confidence

Every stored value carries the source it came from and a confidence score:

| Source | Confidence |
| --- | --- |
| `browser_tab` | 0.88 |
| `accessibility` | 0.80 |
| `window_title` | 0.72 |
| `ocr` | 0.45 |

> **These are ordering priors, not measurements.** They encode the belief that a
> value the app told us directly is more trustworthy than one recovered from
> pixels. They have never been fitted against labelled data. Do not cite them as
> a result — the same caveat that applies to the synthesis confidence weights in
> [UNDER_THE_HOOD.md](UNDER_THE_HOOD.md).

## In the graph

Captured fields become `connector-field` nodes attached to the event's artifact,
each carrying a gate reason naming the manifest, the source and the confidence:

```text
declared by the media_player manifest; read from accessibility (confidence 0.8)
```

So the graph can distinguish a value the app asserted from one recovered by OCR,
which matters when an agent has to decide how much to trust it.

## In the dashboard

The Privacy tab gains two panels:

- **Structured Connectors** — every connector, whether it is active at the
  current depth, the complete list of fields it may store with their storage
  mode, and the explicit denied list.
- **Provenance** — what the connectors actually did: fields seen, mean
  confidence, which source each value came from, and how often a costlier source
  was avoided.

The second panel's *avoided* count is the number worth watching. It is the
direct measure of whether this layer is doing its job.

## Adding a connector

1. Write `digital_twin_sensor/connectors/manifests/<id>.json`. The filename must
   match the `id`.
2. Declare only fields you can justify. Every field needs a `description`; a
   field nobody described is a field nobody reviewed.
3. Declare a `denied` list. It is documentation for reviewers, and the tests
   require it to be non-empty.
4. Add tests to `tests/test_connectors.py` — including a negative test proving
   the connector cannot store something adjacent and tempting.
5. Run the suite. Manifests are validated at load, so a malformed one fails the
   whole load rather than degrading quietly.

## Validation

```bash
python -m unittest discover -s tests
python -m compileall digital_twin_sensor
node --check digital_twin_sensor/ui_static/app.js
```

## Known limits

- Extraction is pattern-based. A title format that changes silently stops
  matching, and nothing currently detects that regression — a per-connector
  match-rate metric in the harness is the obvious next step.
- `dev_workspace` depends on editors putting the repository in the window title.
  Editors that do not are simply not covered.
- Confidence is a prior, not a measurement, as above.
- No connector has been evaluated against labelled outcomes. The
  `context_feedback` labels are the intended first dataset for that.
