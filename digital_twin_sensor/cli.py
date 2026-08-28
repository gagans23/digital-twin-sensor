from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .collectors.macos_active_window import build_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ensure_config, load_config
from .context_pack import PURPOSES, TARGETS, build_context_pack
from .context_graph import build_context_graph
from .fleet import build_fleet_status
from .query import format_retrieval, retrieve
from .redaction import redact_text
from .store import EventStore
from .twin import build_digital_twin_signature
from .web import run_dashboard
from .working_spheres import build_working_spheres


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _toggle(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
        return False
    raise argparse.ArgumentTypeError("expected on/off, true/false, or yes/no")


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


def cmd_graph(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    graph = build_context_graph(
        events,
        config,
        days=args.days,
        max_nodes=args.max_nodes,
        max_edges=args.max_edges,
    )
    print(json.dumps(graph, indent=2))
    return 0


def cmd_activities(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    activities = build_working_spheres(
        events,
        config,
        days=args.days,
        max_spheres=args.max_spheres,
    )
    print(json.dumps(activities, indent=2))
    return 0


def cmd_configure(args: argparse.Namespace) -> int:
    config_path = ensure_config(args.config)
    config = load_config(config_path)

    if args.depth is not None:
        config["context_capture_depth"] = max(0, min(4, int(args.depth)))
    if args.browser_tab_details is not None:
        config["enable_browser_tab_details"] = args.browser_tab_details
    if args.browser_url_path is not None:
        config["browser_tab_store_url_path"] = args.browser_url_path
    if args.browser_url_query is not None:
        config["browser_tab_store_query"] = args.browser_url_query
    if args.fleet_device_name is not None:
        config["fleet_device_name"] = args.fleet_device_name.strip() or config.get("fleet_device_name")
    if args.fleet_control_plane_url is not None:
        config["fleet_control_plane_url"] = args.fleet_control_plane_url.strip()
    if args.fleet_sync is not None:
        config["fleet_sync_enabled"] = args.fleet_sync
    if args.fleet_upload_mode is not None:
        config["fleet_upload_mode"] = args.fleet_upload_mode
    if args.raw_event_upload is not None:
        config["fleet_raw_event_upload"] = args.raw_event_upload

    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    keys = [
        "context_capture_depth",
        "enable_browser_tab_details",
        "browser_tab_detail_min_depth",
        "browser_tab_detail_apps",
        "browser_tab_store_url_path",
        "browser_tab_store_query",
        "fleet_device_id",
        "fleet_device_name",
        "fleet_control_plane_url",
        "fleet_sync_enabled",
        "fleet_upload_mode",
        "fleet_raw_event_upload",
    ]
    print(json.dumps({key: config.get(key) for key in keys}, indent=2))
    return 0


def cmd_fleet(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    total_count = store.count_events(subject_id=subject_id)
    store.close()
    status = build_fleet_status(
        events,
        config,
        db_path=args.db,
        days=args.days,
        total_count=total_count,
    )
    print(json.dumps(status, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    print(json.dumps(events, indent=2))
    return 0


def cmd_context_pack(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = EventStore(args.db)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    pack = build_context_pack(
        events,
        config,
        days=args.days,
        purpose=args.purpose,
        target=args.target,
        sphere_id=args.sphere_id,
        max_events=args.max_events,
    )
    payload = (
        pack.get("export", {}).get("markdown", "")
        if args.format == "markdown"
        else json.dumps(pack, indent=2)
    )
    if args.output:
        output_path = args.output.expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(f"Wrote {args.format} context pack: {output_path}")
    else:
        print(payload, end="" if payload.endswith("\n") else "\n")
    return 0 if pack.get("status") != "blocked" else 1


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

    graph = sub.add_parser("graph", help="Build the privacy-gated living context graph as JSON.")
    graph.add_argument("--subject-id", default=None)
    graph.add_argument("--days", type=int, default=14)
    graph.add_argument("--max-nodes", type=int, default=None)
    graph.add_argument("--max-edges", type=int, default=None)
    graph.set_defaults(func=cmd_graph)

    activities = sub.add_parser("activities", help="Infer working spheres and resume packs as JSON.")
    activities.add_argument("--subject-id", default=None)
    activities.add_argument("--days", type=int, default=14)
    activities.add_argument("--max-spheres", type=int, default=None)
    activities.set_defaults(func=cmd_activities)

    configure = sub.add_parser("configure", help="Update capture depth and safe detail toggles.")
    configure.add_argument("--depth", type=int, choices=range(0, 5), default=None)
    configure.add_argument("--browser-tab-details", type=_toggle, default=None, metavar="on|off")
    configure.add_argument("--browser-url-path", type=_toggle, default=None, metavar="on|off")
    configure.add_argument("--browser-url-query", type=_toggle, default=None, metavar="on|off")
    configure.add_argument("--fleet-device-name", default=None)
    configure.add_argument("--fleet-control-plane-url", default=None)
    configure.add_argument("--fleet-sync", type=_toggle, default=None, metavar="on|off")
    configure.add_argument(
        "--fleet-upload-mode",
        choices=["local_only", "summaries_only", "context_packs_only"],
        default=None,
    )
    configure.add_argument("--raw-event-upload", type=_toggle, default=None, metavar="on|off")
    configure.set_defaults(func=cmd_configure)

    fleet = sub.add_parser("fleet", help="Show local fleet/device management status as JSON.")
    fleet.add_argument("--subject-id", default=None)
    fleet.add_argument("--days", type=int, default=14)
    fleet.set_defaults(func=cmd_fleet)

    context_pack = sub.add_parser(
        "context-pack",
        help="Export a gated working-sphere context pack for Kiro, Codex, GitLab, or a local file.",
    )
    context_pack.add_argument("--subject-id", default=None)
    context_pack.add_argument("--days", type=int, default=14)
    context_pack.add_argument("--purpose", choices=sorted(PURPOSES), default="coding")
    context_pack.add_argument("--target", choices=sorted(TARGETS), default="kiro")
    context_pack.add_argument("--sphere-id", default=None)
    context_pack.add_argument("--max-events", type=int, default=8)
    context_pack.add_argument("--format", choices=["markdown", "json"], default="markdown")
    context_pack.add_argument("--output", type=_path, default=None)
    context_pack.set_defaults(func=cmd_context_pack)

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
