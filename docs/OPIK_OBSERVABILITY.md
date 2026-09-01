# Opik Observability

Operational traces explain whether the pipeline ran, how long each stage took,
and where it failed or withheld context. They are not copies of a person's
activity and are not evidence that a context pack improved their work.

## Architecture

```text
Sensor / dashboard / maintenance commands (Python 3.9+)
  -> fixed operation vocabulary + numeric counts, no content
  -> separate local SQLite operational log (0600, bounded)
       -> dashboard: /#observability
       -> optional exporter worker (Python 3.10+, official Opik SDK)
            -> explicitly configured Opik API (local server or HTTPS)
```

`observability.py` uses only the standard library. The sensor never imports Opik
or waits for network delivery. `opik_exporter.py` uses the official SDK's
synchronous REST clients, pinned to **2.2.45**, so failed HTTP calls cannot be
mistaken for successful background enqueueing. SDK usage analytics, Sentry error
reporting, ambient config discovery, redirects, and ambient HTTP proxies are
disabled. TLS verification stays on.

The current SDK requires Python 3.10+. Do not upgrade or fill the sensor's
Python 3.9 environment with evaluation dependencies just to export telemetry.
Keep the exporter in a separate environment. Opik itself is a separate service;
installing this extra does not install an Opik server.

## What Is Instrumented

| Boundary | Recorded result |
| --- | --- |
| Continuous, CLI, and dashboard collection | sample status, capture/persist durations, stored count |
| Browser, Accessibility, OCR detail adapters | duration, captured/no-result status, safe error category |
| Context-pack admission | ready/blocked/empty and allow/deny/redact counts |
| Learning refresh | card and feedback counts, duration |
| Resume reads and writes | outcome and duration, nested pack checks |
| Overview and query retrieval | duration and bounded child spans |

`no_result` does not distinguish a disabled adapter, an irrelevant app, a missing
permission, or a swallowed provider failure. Use Product Ops to inspect
permissions. `ok` means a function completed, not that its inference was correct.
An idle machine or paused collection produces no collection spans. UI refreshes
produce their own operations. These are operational timestamps, not sampled
foreground dwell. No LLM calls are added, so token usage and model cost are absent.

This is a structured operational log plus traces in Opik, **not** automatic
forwarding of all stdout, OS logs, model prompts, or existing collector logs.
The continuous collector's new status messages omit captured artifact text.
Explicit data commands such as `export` and `collect-once` still display their
requested output; do not pipe those into an external log service.

## Privacy And Delivery Contract

- Off by default. `local` records without network export; `opik` also queues new
  traces for the approved destination. The dashboard can enable local logging
  or turn logging off, but cannot configure external export.
- Allowlisted names, outcomes, numeric counts, timestamps, random IDs, and
  bounded duration only. No app/title/artifact names, domains, URLs, source IDs,
  user/device identity, OCR text, notes, prompts, arguments, return payloads,
  stack traces, attachments, credentials, or arbitrary log messages.
- The same schema is reconstructed before persistence and before export.
  Unknown fields are dropped; unknown operation names are rejected. Error
  messages from either the application or Opik are never retained.
- Logs are plaintext operational metadata even when event-field encryption is
  enabled. Timing can reveal work patterns. Access, consent, and retention still
  matter; this is not anonymization or a privacy proof.
- At most 2,000 root traces and 64 child spans per trace. Seven-day expiry is
  enforced on the next write, status read, or export, not by an independent
  wall-clock deletion service. Old pending traces may expire or be evicted;
  the dashboard exposes that count. Disk-full/locked-log capture can drop a
  trace and emits a rate-limited fixed warning, not an exact global loss counter.
- A short SQLite busy timeout protects collection. Export runs out of process,
  in batches of up to ten roots/two HTTP calls, with five-second network phase
  timeouts and exponential retry delays capped at five minutes. After six
  failed attempts a trace is marked `failed`; there is no automatic replay of
  dead letters. Network timeouts are not a strict end-to-end wall-clock budget.
- A two-minute SQLite lease prevents normal simultaneous exporters; it expires
  after a crash. Stable UUIDv7 IDs are derived from random local trace IDs for
  retries. Delivery is best-effort/at-least-once, not exactly once.
- `accepted` means both trace and span requests received successful HTTP
  responses. It does not independently verify server persistence or visibility.
  A partial upload may already be visible before the retry succeeds.
- Changing mode, destination, project, or workspace invalidates old pending
  records. Local history is **never retroactively uploaded**. Configuration
  generations fence in-flight local recordings. The exporter rechecks consent
  before each request. A request already in flight cannot be recalled.
- Clear local logs removes the operational ledger and invalidates active
  recordings. `purge --all --yes` also clears the operational ledger, even for
  a subject-scoped purge, because operational records carry no subject IDs.
  This does not erase Opik copies or backups. Set remote retention/deletion in
  Opik before enabling export.

## Start With Local Logs

```bash
digital-twin-sensor observability configure --mode local
digital-twin-sensor observability test
digital-twin-sensor observability status
```

Open the dashboard's **Observability** tab. Expand an operation to inspect child
spans, filter errors/blocked outcomes, record a synthetic test, turn logging off,
or clear local records. The test has no captured workstation content.

The log is beside the event database, normally
`~/.digital-twin-sensor/events.observability.sqlite`. For a custom database, place
`--db PATH` **before** `observability` in all commands. Configuration lives in
this separate database; existing capture settings are unchanged.

## Connect An Opik Server

For self-hosting, follow the [official deployment guide](https://www.comet.com/docs/opik/self-host/overview).
The documented local UI/API defaults are `http://localhost:5173` and
`http://localhost:5173/api`; verify the address of your deployment.

For a single-user local evaluation, this repository includes a hardened overlay
for the official Compose stack:

```bash
python3 scripts/manage_local_opik.py start
python3 scripts/manage_local_opik.py status
```

The manager checks out the tested upstream commit into
`~/.digital-twin-sensor/services/opik`, copies private runtime configuration to
`~/.digital-twin-sensor/services/opik-local`, and starts only the frontend plus
its required services. Only `127.0.0.1:5173` is published. Backend, MySQL,
ClickHouse, Redis, ZooKeeper, and MinIO remain on an internal Docker network.
The overlay denies foreign Host/Origin and cross-site browser requests, disables
Opik usage reporting, remote model registry, Opik AI, Ollie, and the Python
evaluation backend, and gives services restart policies. Docker Desktop still
needs to start after login. This is a local development deployment, not a
multi-user production service or a substitute for authentication, backup,
encryption-at-rest, or recovery testing.

Verify persistence using synthetic data before connecting the live ledger:

```bash
~/.digital-twin-sensor/opik-venv/bin/python scripts/verify_local_opik.py
```

The verifier writes only `observability.test` and a blocked `context.pack` child,
reads the trace back by ID, checks that input/output are absent, and applies the
server's shortest supported project retention (`short_14d`). Repeated runs can
create another retention rule; inspect the Opik project configuration if you
change this policy.

From this repository, create a separate worker environment:

```bash
python3.12 -m venv ~/.digital-twin-sensor/opik-venv
~/.digital-twin-sensor/opik-venv/bin/python -m pip install '.[observability]'

digital-twin-sensor observability configure --mode opik \
  --endpoint http://localhost:5173/api \
  --project digital-twin-sensor --workspace default
digital-twin-sensor observability test
~/.digital-twin-sensor/opik-venv/bin/python -m digital_twin_sensor observability export
```

For Opik Cloud, deliberately approve HTTPS export and use your workspace slug:

```bash
digital-twin-sensor observability configure --mode opik \
  --endpoint https://www.comet.com/opik/api \
  --workspace YOUR_WORKSPACE --project digital-twin-sensor --allow-remote
```

Supply the API key to the worker only through `DTS_OPIK_API_KEY`, or a private
file outside the repo with mode `0600` and `--api-key-file PATH`. Do not put keys
in URLs, command arguments, committed files, dashboard fields, or screenshots.
`OPIK_API_KEY` is intentionally not inherited. Use generic project/workspace
identifiers; those routing labels are sent to the server.

Confirm a synthetic trace in Opik before allowing real operational export.
Configuration enables export of **new** operations immediately, so pause local
services or use a separate synthetic `--db` when testing a destination first.

For a foreground worker, add `--watch`. For macOS login persistence:

```bash
python3 scripts/install_opik_agent.py \
  --python ~/.digital-twin-sensor/opik-venv/bin/python
# Remote authenticated deployments also need --api-key-file PATH.
```

The installer validates the dedicated worker, writes a structured LaunchAgent,
and does not reinstall or restart collection. It runs only in the logged-in
user session. Service stdout/stderr go to `/dev/null`; bounded export diagnostics
are in the dashboard. A process that cannot open its log can still need manual
diagnosis with a foreground run. This is not an enterprise service manager.

## Stop, Clear, Troubleshoot

```bash
digital-twin-sensor observability configure --mode off
digital-twin-sensor observability purge
python3 scripts/install_opik_agent.py --uninstall
python3 scripts/manage_local_opik.py stop
```

Stopping the local stack retains its named volumes. Removing remote traces or
volumes is deliberately not bundled with routine shutdown.

`authentication`: check the worker's key file and workspace. `transport`: check
the API URL, DNS, server, and certificate chain. `server`/`rate_limited`: the
bounded queue retries. `request_rejected`: verify server/SDK compatibility.
`sdk_unavailable`: use the separate supported Python environment. `configuration`:
check destination/key configuration and whether settings changed during export.
Pending records with no recent attempt usually mean the worker is not running.
There is no fallback destination and no automatic privacy weakening on failure.

## Verification And Extension Rules

```bash
python -m unittest discover -s tests
node --test tests/dashboard_ui.test.cjs
~/.digital-twin-sensor/opik-venv/bin/python -m unittest tests.test_observability -v
```

SDK contract tests use the actual pinned client against a localhost stub,
including serialization, partial failure, authentication, retries, and a
non-local connection guard. They do not prove compatibility with every server
version, a working cloud account, or persisted traces in a real Opik UI.
Run a synthetic smoke against the approved server before declaring connected.

Do not add `@opik.track` to capture functions: its default input/output capture
would export personal context. Add static operation names to the schema, and
test both storage and wire payloads with private-content canaries. Keep calls
and raw error messages out of metadata. The generated REST client's contract
can change; a dependency upgrade must pass the SDK transport tests.

References: [SDK configuration](https://www.comet.com/docs/opik/tracing/advanced/sdk_configuration),
[Python client reference](https://www.comet.com/docs/opik/python-sdk-reference/Opik.html),
[pinned package](https://pypi.org/project/opik/2.2.45/).

## Release Verification, 1 September 2026

- Rebased on main `1884cd4`; retained the concurrent aggregation work unchanged.
- Python regression suite: 213 tests passed, 19 optional tests skipped in the
  base environment. The focused resume/hardening suite passed 40 tests with two
  encryption-dependent skips.
- Python 3.12 Opik suite: all 16 passed, including those four SDK tests. Repeated
  from outside the checkout against the installed wheel and dedicated worker.
- JavaScript: all 12 tests passed. Syntax, compilation, and diff checks passed.
- Context harness: all five scenarios passed, zero leakage canaries, no baseline
  regression. This is a small regression set, not a production privacy guarantee.
- Installed wheel: connector and UI asset smoke passed. Desktop 1440px and mobile
  390px layouts checked; no document/text overflow. Recording, filtering, logging
  pause, and purge confirmation/cancellation exercised with synthetic data.
- GitHub CI passed for implementation commit `6e33b00`, including the new SDK job.
- Official Opik commit `c0e842537db5d57ef8ed890af38c6180445d667f`
  runs locally with the repository overlay. Health, same-origin UI, and project
  listing passed; an untrusted Origin received HTTP 403. Only frontend port
  `127.0.0.1:5173` is published.
- Synthetic export was accepted and read back by trace ID. The project uses
  `short_14d` server retention. The live exporter LaunchAgent is running and
  accepted continuous collection/learning traces without errors.
- Server inspection found only fixed operation names, absent trace inputs and
  outputs, and allowlisted metadata keys. More than 1,600 pre-existing local
  records remained local and were not retroactively queued. This verifies the
  tested host path, not production security, durable backup, or exactly-once
  delivery.
