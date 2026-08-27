from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .collectors.macos_active_window import build_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ensure_config, load_config
from .query import format_retrieval, retrieve
from .redaction import redact_text
from .store import EventStore
from .twin import build_digital_twin_signature
from .web import run_dashboard


def _path(value: str) -> Path:
    return Path(value).expanduser()


def cmd_init(args: argparse.Namespace) -> int:
    config_path = ensure_config(args.config)
    store = EventStore(args.db)
    store.close()
    print(f"Config: {config_path}")
    print(f"Database: {args.db}")
    print("Initialized. Edit the config before long-running collection if needed.")
    return 0


def cmd_collect_once(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    event = build_event(config, args.dwell_seconds)
    if event is None:
        print("Ignored current app according to config.")
        return 0
    store = EventStore(args.db)
    event_id = store.insert_event(event)
    store.close()
    print(f"Stored event {event_id}: {event['app']} | {event['artifact']} | {event['domain']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    interval = args.interval or int(config.get("sample_interval_seconds", 15))
    store = EventStore(args.db)
    print(f"Collecting active-window attention every {interval}s. Press Ctrl-C to stop.")
    try:
        while True:
            try:
                event = build_event(config, interval)
                if event is not None:
                    store.insert_event(event)
                    if args.verbose:
                        print(
                            f"{event['ts_end']} {event['app']} "
                            f"{event['domain']} {event['artifact']}"
                        )
            except Exception as exc:
                print(f"collector error: {exc}", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        store.close()
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.long_days)
    store.close()
    profile = build_digital_twin_signature(
        events,
        short_days=args.short_days,
        long_days=args.long_days,
    )
    print(json.dumps(profile, indent=2))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()

    profile = build_digital_twin_signature(events, short_days=min(5, args.days), long_days=args.days)
    result = retrieve(args.query, events, profile, top_k=args.top_k)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_retrieval(result))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    print(json.dumps(events, indent=2))
    return 0


def cmd_redact_existing(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)

    changed = 0
    findings_total: dict[str, int] = {}
    for event in events:
        title = redact_text(event["title"], config)
        artifact = redact_text(event["artifact"], config)
        metadata = dict(event.get("metadata", {}))
        findings = dict(metadata.get("redaction_findings", {}))
        for result in (title, artifact):
            for key, value in result.findings.items():
                findings[key] = int(findings.get(key, 0)) + int(value)
                findings_total[key] = int(findings_total.get(key, 0)) + int(value)
        metadata["redaction_findings"] = findings

        if title.text != event["title"] or artifact.text != event["artifact"]:
            changed += 1
            if not args.dry_run:
                store.update_event_text(
                    int(event["id"]),
                    title=title.text,
                    artifact=artifact.text,
                    metadata=metadata,
                )

    store.close()
    mode = "would update" if args.dry_run else "updated"
    print(f"{mode} {changed} events")
    print(json.dumps({"redaction_findings": findings_total}, indent=2))
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    run_dashboard(
        db_path=args.db,
        config_path=args.config,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
        verbose=args.verbose,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="digital-twin-sensor",
        description="Local attention sensor and Digital Twin Signature prototype.",
    )
    parser.add_argument("--db", type=_path, default=DEFAULT_DB_PATH)
    parser.add_argument("--config", type=_path, default=DEFAULT_CONFIG_PATH)

    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create config and SQLite database.")
    init.set_defaults(func=cmd_init)

    collect = sub.add_parser("collect-once", help="Store one active-window focus event.")
    collect.add_argument("--dwell-seconds", type=float, default=15.0)
    collect.set_defaults(func=cmd_collect_once)

    run = sub.add_parser("run", help="Continuously collect active-window focus events.")
    run.add_argument("--interval", type=int, default=None)
    run.add_argument("--verbose", action="store_true")
    run.set_defaults(func=cmd_run)

    profile = sub.add_parser("profile", help="Print the Digital Twin Signature as JSON.")
    profile.add_argument("--subject-id", default=None)
    profile.add_argument("--short-days", type=int, default=5)
    profile.add_argument("--long-days", type=int, default=14)
    profile.set_defaults(func=cmd_profile)

    query = sub.add_parser("query", help="Rank artifacts using attention + content signals.")
    query.add_argument("query")
    query.add_argument("--subject-id", default=None)
    query.add_argument("--days", type=int, default=14)
    query.add_argument("--top-k", type=int, default=8)
    query.add_argument("--json", action="store_true")
    query.set_defaults(func=cmd_query)

    export = sub.add_parser("export", help="Export recent raw events as JSON.")
    export.add_argument("--subject-id", default=None)
    export.add_argument("--days", type=int, default=14)
    export.set_defaults(func=cmd_export)

    redact = sub.add_parser("redact-existing", help="Apply current PII masking rules to stored events.")
    redact.add_argument("--subject-id", default=None)
    redact.add_argument("--days", type=int, default=3650)
    redact.add_argument("--dry-run", action="store_true")
    redact.set_defaults(func=cmd_redact_existing)

    ui = sub.add_parser("ui", help="Launch the local Digital Twin Console.")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-open", action="store_true")
    ui.add_argument("--verbose", action="store_true")
    ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
