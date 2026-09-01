# API Reference

The local dashboard server accepts loopback bindings only. Every API request requires the per-process `X-DTS-Token` header; the local HTML page bootstraps it for the dashboard. Host and Origin checks reject cross-origin requests. This is a local browser boundary, not multi-user authentication or protection from processes running as you.

For scripted calls, load the token without printing or committing it:

```bash
export DTS_TOKEN="$(curl -fsS http://127.0.0.1:8765/ | sed -n 's/.*name="dts-session-token" content="\([^"]*\)".*/\1/p')"
```

The token changes when the server restarts. Reload the dashboard after upgrades.

```bash
digital-twin-sensor ui --no-open --port 8765
```

Base URL:

```text
http://127.0.0.1:8765
```

## Resume Workflow

`GET /api/resume` returns the local gated resume view, saved task identities, and the evidence scope admitted for the selected activity group. `POST /api/resume` accepts checkpoint, start, shown, outcome, save-task, link-task, and unlink-task actions. Identity-dependent writes carry a revision token. These use the same session header and do not add checkpoint notes to agent exports. See [Resume My Work](RESUME_WORKFLOW.md) for schemas, conflict handling, retention, and evidence limits.

## GET /api/overview

Returns the dashboard payload: totals, profile, context graph, working spheres, context pack, surface details, attention depth, fleet posture, recent events, and privacy state.

Query parameters:

| Name | Default | Description |
| --- | --- | --- |
| `days` | `14` | Window of events to analyze |
| `limit` | `80` | Maximum recent events to include |

Example:

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" 'http://127.0.0.1:8765/api/overview?days=14&limit=20'
```

## GET /api/health

Returns product doctor output: service state, sample freshness, permission posture, privacy checks, implemented extensions, paper deviations, product gaps, and research backlog.

Example:

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" 'http://127.0.0.1:8765/api/health'
```

## GET /api/context-pack

Builds a gated context pack.

Query parameters:

| Name | Default | Description |
| --- | --- | --- |
| `days` | `14` | Event window |
| `purpose` | `coding` | Recognized purpose for the Memory Admission Gate; empty or unknown values return HTTP 400 |
| `target` | `kiro` | Export target, such as `kiro`, `codex`, `gitlab`, or `local_file` |
| `sphere_id` | empty | Optional working-sphere id |
| `max_events` | `8` | Maximum admitted evidence events |

Example:

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" 'http://127.0.0.1:8765/api/context-pack?target=gitlab&purpose=coding'
```

## GET /api/learning

Returns local feedback labels, evolving context cards, and maintenance state.

Query parameters:

| Name | Default | Description |
| --- | --- | --- |
| `days` | `14` | Event window used to refresh cards |
| `max_cards` | `12` | Maximum context cards to return |

Example:

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" 'http://127.0.0.1:8765/api/learning?days=14'
```

## POST /api/feedback

Stores a redacted local feedback label for a pack, sphere, or evidence item.

Example:

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" -X POST 'http://127.0.0.1:8765/api/feedback' \
  -H 'Content-Type: application/json' \
  -d '{"pack_id":"pack_xxx","sphere_id":"sphere_xxx","scope":"pack","label":"useful"}'
```

## POST /api/feedback/resolve

Resolves one restriction for the configured subject. Send JSON `{"feedback_id":123}`. Unresolved `too_private`, `wrong`, and `stale` feedback blocks matching packs across targets. Resolution is explicit and does not delete the feedback history. Successful resolution permits rebuilding a pack; other restrictions may still block it.

## GET /api/query

Runs attention-weighted evidence retrieval.

Query parameters:

| Name | Default | Description |
| --- | --- | --- |
| `q` | empty | Query text |
| `days` | `14` | Event window |
| `top_k` | `8` | Number of results |

Example:

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" 'http://127.0.0.1:8765/api/query?q=what%20did%20I%20return%20to'
```

## GET /api/fleet

Returns local endpoint posture, active policy, connector inventory, and summary-sync readiness.

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" 'http://127.0.0.1:8765/api/fleet'
```

## POST /api/collect-once

Collects one foreground sample unless collection is paused or the current app is ignored.

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" -X POST 'http://127.0.0.1:8765/api/collect-once'
```

## POST /api/admin/watchdog

Runs a local self-heal check and restarts stale services when needed.

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" -X POST 'http://127.0.0.1:8765/api/admin/watchdog'
```

## POST /api/admin/pause

Pauses collection without uninstalling services.

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" -X POST 'http://127.0.0.1:8765/api/admin/pause'
```

## POST /api/admin/resume

Resumes collection.

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" -X POST 'http://127.0.0.1:8765/api/admin/resume'
```

## POST /api/admin/purge-retention

Deletes events older than the configured retention window. This endpoint requires a confirmation query parameter.

```bash
curl -H 'X-DTS-Token: '"$DTS_TOKEN" -X POST 'http://127.0.0.1:8765/api/admin/purge-retention?confirm=purge-retention'
```

## Security Notes

- The API is intended for local use only.
- All API reads and writes require the local session header.
- Remote bindings are rejected. A future remote service needs separate identity, authorization, TLS, audit, and consent design.
