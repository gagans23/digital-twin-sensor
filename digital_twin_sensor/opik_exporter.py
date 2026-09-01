"""Explicit, synchronous Opik export, run separately from the sensor process."""
from __future__ import annotations

import json
import os
import stat
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import observability as obs


def _sdk():
    if sys.version_info < (3, 10):
        raise RuntimeError("Use a separate Python 3.10+ environment with the observability extra")
    # Set before importing Opik: its package initializer configures error reporting.
    os.environ.update({"OPIK_ANALYTICS_ENABLE": "false", "OPIK_SENTRY_ENABLE": "false",
                       "OPIK_CONSOLE_LOGGING_LEVEL": "CRITICAL", "OPIK_FILE_LOGGING_LEVEL": "CRITICAL",
                       "OPIK_LOGGING_FILE": os.devnull, "OPIK_CONFIG_PATH": os.devnull,
                       "LITELLM_LOCAL_MODEL_COST_MAP": "True"})
    from opik.rest_api.client import OpikApi
    from opik.rest_api.types.trace_write import TraceWrite
    from opik.rest_api.types.span_write import SpanWrite
    import httpx
    import uuid6
    return OpikApi, TraceWrite, SpanWrite, httpx, uuid6


def _api_key(key_file=None):
    if key_file:
        path = Path(key_file).expanduser()
        if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("API key file must be private (chmod 600), not a symlink")
        key = path.read_text(encoding="utf-8").strip()
    else:
        key = os.environ.get("DTS_OPIK_API_KEY", "").strip()
    if len(key) > 4096 or any(char.isspace() for char in key):
        raise ValueError("Invalid API key format")
    return key or None


def _error(exc):
    code = getattr(exc, "status_code", None)
    if code in (401, 403):
        return "authentication"
    if code == 429:
        return "rate_limited"
    if type(code) is int:
        return "server" if code >= 500 else "request_rejected"
    if isinstance(exc, ImportError) or (sys.version_info < (3, 10)):
        return "sdk_unavailable"
    if isinstance(exc, (ValueError, RuntimeError)):
        return "configuration"
    return "transport"


def _wire(trace, config, TraceWrite, SpanWrite, uuid6):
    def identifier(value):
        # Stable across retries, random per operation; no subject/evidence identifiers.
        bits = (int(trace["start"] * 1000) << 80) | (uuid.UUID(value).int & ((1 << 80)-1))
        return str(uuid6.UUID(int=bits, version=7))

    def fields(span):
        start = datetime.fromtimestamp(span["start"], timezone.utc)
        result = {"id": identifier(span["id"]), "project_name": config["project"],
                  "name": span["name"], "start_time": start,
                  "end_time": start + timedelta(milliseconds=span["duration_ms"]),
                  "tags": ["dts-operations-v1", span["outcome"]],
                  "metadata": {"schema": "dts-operations-v1", "outcome": span["outcome"],
                               "error_category": span["error"], **span["counts"]}}
        if span["outcome"] == "error":
            result["error_info"] = {"exception_type": span["error"], "message": "Operation failed; content withheld"}
        return result

    root = TraceWrite(**fields(trace))
    spans = []
    retained = {item["id"] for item in trace["spans"]}
    for span in trace["spans"]:
        parent_id = span["parent_id"]
        spans.append(SpanWrite(**fields(span), trace_id=identifier(trace["id"]),
                               parent_span_id=identifier(parent_id) if parent_id in retained else None,
                               type="guardrail" if span["name"] == "context.pack" else "general"))
    return root, spans


def export_once(db_path, *, key_file=None):
    """At most ten traces/two requests; acknowledge only successful SDK HTTP calls."""
    cfg = obs.settings(db_path)
    if cfg["mode"] != "opik":
        return {"status": "disabled", "accepted": 0}
    lease = time.time() + 120
    with obs.connect(db_path, timeout=0.1) as conn:
        conn.execute("BEGIN IMMEDIATE")
        obs._prune(conn, time.time())
        if conn.execute("SELECT lease_until FROM exporter WHERE id=1").fetchone()[0] > time.time():
            return {"status": "busy", "accepted": 0}
        rows = conn.execute("SELECT * FROM records WHERE state='pending' AND destination=? AND next_attempt<=? ORDER BY created LIMIT 10",
                            (obs.destination(cfg), time.time())).fetchall()
        if not rows:
            conn.commit()
            return {"status": "idle", "accepted": 0}
        conn.execute("UPDATE exporter SET lease_until=?,last_attempt=? WHERE id=1", (lease, time.time()))
        conn.commit()

    def still_allowed():
        if obs.settings(db_path) != cfg:
            raise RuntimeError("Export configuration changed")
        with obs.connect(db_path) as conn:
            return all(conn.execute("SELECT 1 FROM records WHERE id=? AND state='pending'", (row["id"],)).fetchone() for row in rows)

    try:
        key = _api_key(key_file)
        remote = urlsplit(cfg["endpoint"]).hostname not in {"127.0.0.1", "localhost", "::1"}
        if remote and not key:
            raise ValueError("Set DTS_OPIK_API_KEY or provide --api-key-file for remote export")
        OpikApi, TraceWrite, SpanWrite, httpx, uuid6 = _sdk()
        traces, spans = [], []
        for row in rows:
            root, children = _wire(obs.safe_trace(json.loads(row["payload"])), cfg, TraceWrite, SpanWrite, uuid6)
            traces.append(root)
            spans.extend(children)
        # No ambient proxies, automatic redirects, authentication discovery, or SDK retry loop.
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as transport:
            client = OpikApi(base_url=cfg["endpoint"], workspace_name=cfg["workspace"], api_key=key,
                             timeout=5, httpx_client=transport)
            if not still_allowed():
                return {"status": "cancelled", "accepted": 0}
            client.traces.create_traces(traces=traces, request_options={"timeout_in_seconds": 5, "max_retries": 0})
            if spans:
                if not still_allowed():
                    return {"status": "cancelled", "accepted": 0}
                client.spans.create_spans(spans=spans, request_options={"timeout_in_seconds": 5, "max_retries": 0})
        with obs.connect(db_path, timeout=2) as conn:
            conn.executemany("UPDATE records SET state='accepted' WHERE id=? AND state='pending'", [(row["id"],) for row in rows])
            conn.execute("UPDATE exporter SET last_success=?,last_error='',accepted=accepted+? WHERE id=1", (time.time(), len(rows)))
            conn.commit()
        return {"status": "accepted", "accepted": len(rows)}
    except Exception as exc:
        category = _error(exc)
        with obs.connect(db_path, timeout=2) as conn:
            for row in rows:
                attempts = row["attempts"] + 1
                conn.execute("UPDATE records SET attempts=?,next_attempt=?,state=? WHERE id=? AND state='pending'",
                             (attempts, time.time()+min(300, 5*2**attempts), "failed" if attempts >= 6 else "pending", row["id"]))
            conn.execute("UPDATE exporter SET last_error=?,failures=failures+1 WHERE id=1", (category,))
            conn.commit()
        return {"status": "error", "error": category, "accepted": 0}
    finally:
        with obs.connect(db_path, timeout=2) as conn:
            conn.execute("UPDATE exporter SET lease_until=0 WHERE id=1 AND lease_until=?", (lease,))
            conn.commit()


def cmd_observability(args):
    try:
        if args.observability_command == "configure":
            result = obs.configure(args.db, mode=args.mode, endpoint=args.endpoint, project=args.project,
                                   workspace=args.workspace, allow_remote=args.allow_remote)
        elif args.observability_command == "purge":
            result = obs.purge(args.db)
        elif args.observability_command == "test":
            if obs.settings(args.db)["mode"] == "off":
                raise ValueError("Enable local or opik mode before recording a synthetic test")
            with obs.operation(args.db, "observability.test"):
                with obs.operation(args.db, "context.pack") as span:
                    span.outcome("blocked")
                    span.counts(deny=1)
            result = obs.status(args.db)
        elif args.observability_command == "export":
            while True:
                result = export_once(args.db, key_file=args.api_key_file)
                print(json.dumps(result), flush=True)
                if not args.watch:
                    return 1 if result["status"] == "error" else 0
                time.sleep(max(2, min(300, args.interval)))
        else:
            result = obs.status(args.db)
        print(json.dumps(result, indent=2))
        return 0
    except KeyboardInterrupt:
        return 0
    except ValueError as exc:
        # Only our configuration validation errors; raw SDK errors are handled above.
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        print("Operational log unavailable; no telemetry configuration changed", file=sys.stderr)
        return 1


def add_observability_parser(sub):
    parser = sub.add_parser("observability", help="Private operational logs and opt-in Opik export.")
    actions = parser.add_subparsers(dest="observability_command", required=True)
    for name in ("status", "test", "purge"):
        actions.add_parser(name).set_defaults(func=cmd_observability)
    configure = actions.add_parser("configure")
    configure.add_argument("--mode", choices=["off", "local", "opik"], required=True)
    configure.add_argument("--endpoint")
    configure.add_argument("--project")
    configure.add_argument("--workspace")
    configure.add_argument("--allow-remote", action="store_true")
    configure.set_defaults(func=cmd_observability)
    exporter = actions.add_parser("export")
    exporter.add_argument("--api-key-file", type=Path)
    exporter.add_argument("--watch", action="store_true")
    exporter.add_argument("--interval", type=int, default=15)
    exporter.set_defaults(func=cmd_observability)
