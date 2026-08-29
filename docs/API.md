# API Reference

The local dashboard server binds to `127.0.0.1` by default.

```bash
digital-twin-sensor ui --no-open --port 8765
```

Base URL:

```text
http://127.0.0.1:8765
```

## GET /api/overview

Returns the dashboard payload: totals, profile, context graph, working spheres, context pack, surface details, attention depth, fleet posture, recent events, and privacy state.

Query parameters:

| Name | Default | Description |
| --- | --- | --- |
| `days` | `14` | Window of events to analyze |
| `limit` | `80` | Maximum recent events to include |

Example:

```bash
curl 'http://127.0.0.1:8765/api/overview?days=14&limit=20'
```

## GET /api/health

Returns product doctor output: service state, sample freshness, permission posture, privacy checks, implemented extensions, paper deviations, product gaps, and research backlog.

Example:

```bash
curl 'http://127.0.0.1:8765/api/health'
```

## GET /api/context-pack

Builds a gated context pack.

Query parameters:

| Name | Default | Description |
| --- | --- | --- |
| `days` | `14` | Event window |
| `purpose` | `coding` | Purpose for the Memory Admission Gate |
| `target` | `kiro` | Export target, such as `kiro`, `codex`, `gitlab`, or `local_file` |
| `sphere_id` | empty | Optional working-sphere id |
| `max_events` | `8` | Maximum admitted evidence events |

Example:

```bash
curl 'http://127.0.0.1:8765/api/context-pack?target=gitlab&purpose=gitlab'
```

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
curl 'http://127.0.0.1:8765/api/query?q=what%20did%20I%20return%20to'
```

## GET /api/fleet

Returns local endpoint posture, active policy, connector inventory, and summary-sync readiness.

```bash
curl 'http://127.0.0.1:8765/api/fleet'
```

## POST /api/collect-once

Collects one foreground sample unless collection is paused or the current app is ignored.

```bash
curl -X POST 'http://127.0.0.1:8765/api/collect-once'
```

## POST /api/admin/watchdog

Runs a local self-heal check and restarts stale services when needed.

```bash
curl -X POST 'http://127.0.0.1:8765/api/admin/watchdog'
```

## POST /api/admin/pause

Pauses collection without uninstalling services.

```bash
curl -X POST 'http://127.0.0.1:8765/api/admin/pause'
```

## POST /api/admin/resume

Resumes collection.

```bash
curl -X POST 'http://127.0.0.1:8765/api/admin/resume'
```

## POST /api/admin/purge-retention

Deletes events older than the configured retention window. This endpoint requires a confirmation query parameter.

```bash
curl -X POST 'http://127.0.0.1:8765/api/admin/purge-retention?confirm=purge-retention'
```

## Security Notes

- The API is intended for local use only.
- It has no authentication layer yet.
- Do not bind it to a public interface without TLS, authentication, audit logs, consent workflows, and retention controls.
