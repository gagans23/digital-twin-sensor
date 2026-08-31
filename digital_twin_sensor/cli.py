from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

from .collectors.macos_active_window import build_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ensure_config, load_config, write_config
from .harness import format_report_markdown, load_scenarios, run_harness
from .synthesis import format_synthesis_markdown, subject_key, synthesize_collective
from .context_pack import PURPOSES, TARGETS, build_context_pack
from .context_graph import build_context_graph
from .fleet import build_fleet_status
from .health import build_health_report, format_health_report, run_watchdog
from .learning import FEEDBACK_LABELS, LearningStore, build_learning_state
from .query import format_retrieval, retrieve
from .redaction import redact_text
from .store import EventStore, open_event_store, utc_now
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
    config = load_config(config_path)
    store = open_event_store(args.db, config)
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
    store = open_event_store(args.db, config)
    event_id = store.insert_event(event)
    store.close()
    print(f"Stored event {event_id}: {event['app']} | {event['artifact']} | {event['domain']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    interval = args.interval or int(config.get("sample_interval_seconds", 15))
    store = open_event_store(args.db, config)
    print(f"Collecting active-window attention every {interval}s. Press Ctrl-C to stop.")
    paused_logged = False
    try:
        while True:
            try:
                config = load_config(args.config)
                if bool(store.cipher) != bool(config.get("encrypt_at_rest", False)):
                    store.close()
                    store = open_event_store(args.db, config)
                interval = args.interval or int(config.get("sample_interval_seconds", 15))
                if config.get("collection_paused", False):
                    if args.verbose and not paused_logged:
                        print("collection paused by config")
                    paused_logged = True
                    time.sleep(interval)
                    continue
                paused_logged = False
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


def cmd_pause(args: argparse.Namespace) -> int:
    config_path = ensure_config(args.config)
    config = load_config(config_path)
    config["collection_paused"] = True
    write_config(config, config_path)
    print("Collection paused. Background services stay installed, but no new focus events are stored.")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    config_path = ensure_config(args.config)
    config = load_config(config_path)
    config["collection_paused"] = False
    write_config(config, config_path)
    print("Collection resumed.")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = open_event_store(args.db, config)
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
    store = open_event_store(args.db, config)
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
    store = open_event_store(args.db, config)
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
    store = open_event_store(args.db, config)
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
    if args.accessibility_surface_details is not None:
        config["enable_accessibility_surface_details"] = args.accessibility_surface_details
    if args.accessibility_app:
        existing = [str(item) for item in config.get("accessibility_surface_detail_apps", [])]
        seen = {item.lower() for item in existing}
        for app in args.accessibility_app:
            name = app.strip()
            if name and name.lower() not in seen:
                existing.append(name)
                seen.add(name.lower())
        config["accessibility_surface_detail_apps"] = existing
    if args.ocr_surface_details is not None:
        config["enable_ocr_surface_details"] = args.ocr_surface_details
    if args.ocr_app:
        existing = [str(item) for item in config.get("ocr_surface_detail_apps", [])]
        seen = {item.lower() for item in existing}
        for app in args.ocr_app:
            name = app.strip()
            if name and name.lower() not in seen:
                existing.append(name)
                seen.add(name.lower())
        config["ocr_surface_detail_apps"] = existing
    if args.ocr_max_lines is not None:
        config["ocr_surface_max_lines"] = max(1, min(40, int(args.ocr_max_lines)))
    if args.ocr_min_confidence is not None:
        config["ocr_surface_min_confidence"] = max(0.0, min(1.0, float(args.ocr_min_confidence)))
    if args.ocr_provider is not None:
        config["ocr_surface_provider"] = args.ocr_provider
    if args.ocr_tesseract_binary is not None:
        config["ocr_tesseract_binary"] = args.ocr_tesseract_binary.strip() or "tesseract"
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

    write_config(config, config_path)

    keys = [
        "context_capture_depth",
        "enable_browser_tab_details",
        "browser_tab_detail_min_depth",
        "browser_tab_detail_apps",
        "browser_tab_store_url_path",
        "browser_tab_store_query",
        "enable_accessibility_surface_details",
        "accessibility_surface_min_depth",
        "accessibility_surface_detail_apps",
        "enable_ocr_surface_details",
        "ocr_surface_min_depth",
        "ocr_surface_detail_apps",
        "ocr_surface_provider",
        "ocr_surface_max_lines",
        "ocr_surface_min_confidence",
        "ocr_tesseract_binary",
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
    store = open_event_store(args.db, config)
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


def cmd_doctor(args: argparse.Namespace) -> int:
    report = build_health_report(
        db_path=args.db,
        config_path=args.config,
        stale_after_seconds=args.stale_after,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_health_report(report))
    return 0 if report["status"] != "blocked" else 2


def cmd_watchdog(args: argparse.Namespace) -> int:
    result = run_watchdog(
        db_path=args.db,
        config_path=args.config,
        stale_after_seconds=args.stale_after,
        fix=args.fix,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_health_report(result["report"]))
        if result["actions"]:
            print("")
            print("Actions:")
            for action in result["actions"]:
                detail = f" {action.get('detail', '')}" if action.get("detail") else ""
                print(f"- {action['status']}: {action['service']}{detail}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = open_event_store(args.db, config)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    print(json.dumps(events, indent=2))
    return 0


def cmd_context_pack(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    config = {**config, "subject_id": subject_id}
    store = open_event_store(args.db, config)
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
        db_path=args.db,
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


def cmd_feedback(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = LearningStore(args.db, config=config)
    try:
        if args.feedback_command == "resolve":
            resolved = store.resolve_feedback(subject_id=subject_id, feedback_id=args.feedback_id)
            print(json.dumps({"resolved": resolved}))
            return 0 if resolved else 1
        if args.feedback_command == "add":
            feedback = store.add_feedback(
                subject_id=subject_id,
                pack_id=args.pack_id,
                sphere_id=args.sphere_id,
                evidence_key=args.evidence_key,
                scope=args.scope,
                label=args.label,
                purpose=args.purpose,
                target=args.target,
                note=args.note or "",
                metadata={"source": "cli"},
                config=config,
            )
            print(json.dumps(feedback, indent=2))
            return 0

        rows = store.list_feedback(subject_id=subject_id, limit=args.limit)
        print(json.dumps({"feedback": rows}, indent=2))
        return 0
    finally:
        store.close()


def cmd_learning(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = open_event_store(args.db, config)
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    state = build_learning_state(
        events,
        config,
        subject_id=subject_id,
        db_path=args.db,
        days=args.days,
        max_cards=args.max_cards,
    )
    if args.format == "json":
        print(json.dumps(state, indent=2))
        return 0

    stats = state["stats"]
    print("# Learning Mode")
    print("")
    print(f"- Policy: {state['policy']}")
    print(f"- Feedback labels: {stats['feedback_count']}")
    print(f"- Context cards: {stats['context_cards']}")
    print(f"- Needs review: {stats['needs_review']}")
    print("")
    for card in state["cards"]:
        print(f"## {card['title']}")
        print(f"- Status: {card['status']}")
        print(f"- Confidence: {round(float(card['confidence']) * 100)}%")
        print(f"- Evidence: {card['evidence_count']} events")
        print(f"- Feedback: {card['useful_count']} useful, {card['issue_count']} issues, {card['privacy_count']} privacy")
        print(f"- Next: {card['next_actions'][0] if card['next_actions'] else 'label the next pack'}")
        print("")
    return 0


def cmd_maintain_learning(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = open_event_store(args.db, config)
    store.delete_before(subject_id=subject_id, cutoff=utc_now() - timedelta(days=max(1, int(config.get("retention_days", 30)))))
    events = store.fetch_window(subject_id=subject_id, days=args.days)
    store.close()
    state = build_learning_state(
        events,
        config,
        subject_id=subject_id,
        db_path=args.db,
        days=args.days,
        max_cards=args.max_cards,
    )
    result = {
        "status": "maintained",
        "generated_at": utc_now().isoformat(),
        "subject_id": subject_id,
        "days": args.days,
        "stats": state["stats"],
        "maintenance": state["maintenance"],
    }
    if not args.quiet:
        print(json.dumps(result, indent=2 if args.pretty else None))
    return 0


def cmd_redact_existing(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = open_event_store(args.db, config)
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


def cmd_purge(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Refusing to delete without --yes.")
        return 2

    config = load_config(args.config)
    subject_id = args.subject_id or config["subject_id"]
    store = open_event_store(args.db, config)
    try:
        if args.all:
            deleted = store.delete_all(subject_id=subject_id)
            mode = "all local events"
        else:
            days = max(0, int(args.older_than_days))
            cutoff = utc_now() - timedelta(days=days)
            deleted = store.delete_before(cutoff=cutoff, subject_id=subject_id)
            mode = f"events older than {days} days"
    finally:
        store.close()

    print(json.dumps({"deleted": deleted, "scope": mode, "subject_id": subject_id}, indent=2))
    return 0



def cmd_harness(args: argparse.Namespace) -> int:
    """Score context packs against the golden set. Non-zero exit on any leak.

    With --baseline, also diff against the last accepted scores: a system
    drifting downward inside the floor still fails, because that drift is
    invisible to a pass/fail gate.
    """
    from .baseline import compare, format_comparison, load_baseline, write_baseline  # noqa: PLC0415

    config = load_config(args.config) if args.config.exists() else None
    scenarios = load_scenarios(args.scenarios) if args.scenarios else None
    report = run_harness(scenarios, config, fail_under=args.fail_under)

    comparison = None
    if args.baseline:
        if not args.baseline.exists():
            print(f"no baseline at {args.baseline}; write one with --update-baseline", file=sys.stderr)
            return 2
        comparison = compare(report, load_baseline(args.baseline))

    if args.format == "json":
        payload = dict(report)
        if comparison is not None:
            payload["baseline"] = {
                "ok": comparison["ok"],
                "regressions": comparison["regressions"],
                "improvements": comparison["improvements"],
                "notes": comparison["notes"],
            }
        rendered = json.dumps(payload, indent=2)
    else:
        rendered = format_report_markdown(report)
        if comparison is not None:
            rendered += format_comparison(comparison)

    print(rendered, end="" if args.format == "markdown" else "\n")
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")

    if args.update_baseline:
        write_baseline(report, args.update_baseline)
        print(f"baseline written to {args.update_baseline}", file=sys.stderr)

    if not report["ok"]:
        return 1
    if comparison is not None and not comparison["ok"]:
        return 1
    return 0


def cmd_synthesize(args: argparse.Namespace) -> int:
    """Fold per-subject working spheres into themes that clear an aggregation floor."""
    if args.input:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        bundles = payload if isinstance(payload, list) else payload.get("bundles", [])
    else:
        config = load_config(args.config)
        store = open_event_store(args.db, config)
        try:
            events = store.fetch_window(
                subject_id=args.subject_id or config["subject_id"], days=args.days
            )
        finally:
            store.close()
        bundles = [
            {
                "subject_key": subject_key(config.get("device_id", "local")),
                "activities": build_working_spheres(events, config, days=args.days),
            }
        ]

    result = synthesize_collective(
        bundles, min_subjects=args.min_subjects, days=args.days
    )
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(format_synthesis_markdown(result), end="")
    return 0



def cmd_resume_study(args: argparse.Namespace) -> int:
    """Measure task-resume time from the local attention trace.

    The one number this project promises and has never had (docs/VALIDATION.md
    V2). Reads the existing store; collects nothing new; sends nothing anywhere.
    """
    from .resume_study import format_resume_study_markdown, run_resume_study  # noqa: PLC0415

    config = load_config(args.config)
    store = open_event_store(args.db, config)
    try:
        events = store.fetch_window(
            subject_id=args.subject_id or config["subject_id"], days=args.days
        )
    finally:
        store.close()

    report = run_resume_study(
        events,
        days=args.days,
        gap_minutes=args.gap_minutes,
        substantive_seconds=args.substantive_seconds,
        block_days=args.block_days,
    )
    rendered = json.dumps(report, indent=2) if args.format == "json" else format_resume_study_markdown(report)
    print(rendered, end="" if args.format == "markdown" else "\n")
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


def cmd_deep_harness(args: argparse.Namespace) -> int:
    """Judgement-based evaluation with deep agents. Optional extra; the
    deterministic harness remains the CI gate."""
    from .deep_harness import DeepEvalUnavailable, run_deep_harness  # noqa: PLC0415

    try:
        report = run_deep_harness(model=args.model, prompt=args.prompt)
    except DeepEvalUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # a judge failing must not look like a clean pass
        print(f"deep harness failed: {exc}", file=sys.stderr)
        return 3
    print(report)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    return 0



def cmd_encrypt_store(args: argparse.Namespace) -> int:
    """Enable encryption at rest and migrate existing rows in place."""
    from .crypto import (  # noqa: PLC0415
        CryptoUnavailable,
        FieldCipher,
        encrypt_event,
        key_file_path,
        load_or_create_key,
        load_existing_key,
    )

    config = load_config(args.config)
    if args.status:
        store = open_event_store(args.db, config)
        try:
            print(json.dumps({"encrypt_at_rest": bool(config.get("encrypt_at_rest", False)),
                              "events": store.count_events(), "key_created": False,
                              "encrypted_fields": ["title", "artifact", "metadata", "learning text"],
                              "not_encrypted": ["timestamps", "app", "domain", "subject_id", "feedback labels"]}, indent=2))
        finally:
            store.close()
        return 0
    try:
        key, origin = (load_existing_key(args.db) if config.get("encrypt_at_rest") else load_or_create_key(args.db))
        cipher = FieldCipher(key)
    except CryptoUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 2

    store = EventStore(args.db, cipher=cipher)
    try:
        total = store.count_events()
        if origin.endswith("key file") or origin.endswith("key file (created)"):
            print(
                f"WARNING: the key is in {key_file_path(args.db)}, not the OS keychain. "
                "Any process running as you can read it.",
                file=sys.stderr,
            )

        # Enable first: concurrent collectors must encrypt new rows throughout
        # migration. A partial migration remains readable and can be resumed.
        config["encrypt_at_rest"] = True
        write_config(config, args.config)
        store.conn.execute("UPDATE storage_policy SET encryption_required = 1 WHERE id = 1")
        store.conn.commit()
        migrated = 0
        for event in store.fetch_events():
            enc = encrypt_event(event, cipher)
            if enc.get("title") != event.get("title"):
                store.update_event_text(
                    event["id"], title=enc["title"], artifact=enc["artifact"], metadata=enc["metadata"]
                )
                migrated += 1
        learning = LearningStore(args.db, cipher=cipher)
        try:
            learning.migrate_encryption()
        finally:
            learning.close()
        store.conn.execute("VACUUM")
        print(f"encryption enabled · key from {origin} · {migrated}/{total} rows migrated")
        print("Reads stay correct during a partial migration: rows written before "
              "encryption decrypt to themselves.")
        return 0
    finally:
        store.close()


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

    pause = sub.add_parser("pause", help="Pause collection without uninstalling services.")
    pause.set_defaults(func=cmd_pause)

    resume = sub.add_parser("resume", help="Resume collection after a pause.")
    resume.set_defaults(func=cmd_resume)

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
    configure.add_argument("--accessibility-surface-details", type=_toggle, default=None, metavar="on|off")
    configure.add_argument("--accessibility-app", action="append", default=[], metavar="APP")
    configure.add_argument("--ocr-surface-details", type=_toggle, default=None, metavar="on|off")
    configure.add_argument("--ocr-app", action="append", default=[], metavar="APP")
    configure.add_argument("--ocr-max-lines", type=int, default=None)
    configure.add_argument("--ocr-min-confidence", type=float, default=None)
    configure.add_argument("--ocr-provider", choices=["apple_vision", "tesseract"], default=None)
    configure.add_argument("--ocr-tesseract-binary", default=None)
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

    doctor = sub.add_parser("doctor", help="Run product health, permission, privacy, and paper-gap diagnostics.")
    doctor.add_argument("--stale-after", type=int, default=180)
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    watchdog = sub.add_parser("watchdog", help="Check service freshness and optionally restart stale services.")
    watchdog.add_argument("--stale-after", type=int, default=180)
    watchdog.add_argument("--fix", action="store_true")
    watchdog.add_argument("--json", action="store_true")
    watchdog.set_defaults(func=cmd_watchdog)

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

    feedback = sub.add_parser("feedback", help="Capture or list local learning labels for context packs.")
    feedback_sub = feedback.add_subparsers(dest="feedback_command", required=True)
    feedback_add = feedback_sub.add_parser("add", help="Add a redacted feedback label.")
    feedback_add.add_argument("--subject-id", default=None)
    feedback_add.add_argument("--pack-id", required=True)
    feedback_add.add_argument("--sphere-id", default=None)
    feedback_add.add_argument("--evidence-key", default=None)
    feedback_add.add_argument("--scope", choices=["pack", "sphere", "evidence"], default="pack")
    feedback_add.add_argument("--label", choices=sorted(FEEDBACK_LABELS), required=True)
    feedback_add.add_argument("--purpose", choices=sorted(PURPOSES), default="coding")
    feedback_add.add_argument("--target", choices=sorted(TARGETS), default="kiro")
    feedback_add.add_argument("--note", default="")
    feedback_add.set_defaults(func=cmd_feedback)
    feedback_list = feedback_sub.add_parser("list", help="List local learning labels.")
    feedback_list.add_argument("--subject-id", default=None)
    feedback_list.add_argument("--limit", type=int, default=50)
    feedback_list.set_defaults(func=cmd_feedback)
    feedback_resolve = feedback_sub.add_parser("resolve", help="Explicitly resolve a reviewed feedback restriction.")
    feedback_resolve.add_argument("--subject-id", default=None)
    feedback_resolve.add_argument("--feedback-id", type=int, required=True)
    feedback_resolve.set_defaults(func=cmd_feedback)

    learning = sub.add_parser("learning", help="Show evolving context cards and feedback-learning state.")
    learning.add_argument("--subject-id", default=None)
    learning.add_argument("--days", type=int, default=14)
    learning.add_argument("--max-cards", type=int, default=12)
    learning.add_argument("--format", choices=["markdown", "json"], default="markdown")
    learning.set_defaults(func=cmd_learning)

    maintain_learning = sub.add_parser(
        "maintain-learning",
        help="Refresh local context cards from redacted traces and feedback labels.",
    )
    maintain_learning.add_argument("--subject-id", default=None)
    maintain_learning.add_argument("--days", type=int, default=14)
    maintain_learning.add_argument("--max-cards", type=int, default=20)
    maintain_learning.add_argument("--quiet", action="store_true")
    maintain_learning.add_argument("--pretty", action="store_true")
    maintain_learning.set_defaults(func=cmd_maintain_learning)

    export = sub.add_parser("export", help="Export recent raw events as JSON.")
    export.add_argument("--subject-id", default=None)
    export.add_argument("--days", type=int, default=14)
    export.set_defaults(func=cmd_export)

    redact = sub.add_parser("redact-existing", help="Apply current PII masking rules to stored events.")
    redact.add_argument("--subject-id", default=None)
    redact.add_argument("--days", type=int, default=3650)
    redact.add_argument("--dry-run", action="store_true")
    redact.set_defaults(func=cmd_redact_existing)

    purge = sub.add_parser("purge", help="Delete local events for retention or reset.")
    purge.add_argument("--subject-id", default=None)
    purge_mode = purge.add_mutually_exclusive_group(required=True)
    purge_mode.add_argument("--older-than-days", type=int, default=None)
    purge_mode.add_argument("--all", action="store_true")
    purge.add_argument("--yes", action="store_true")
    purge.set_defaults(func=cmd_purge)

    harness = sub.add_parser(
        "harness",
        help="Score context packs against the golden set. Exits non-zero on any leak.",
    )
    harness.add_argument("--scenarios", type=_path, default=None)
    harness.add_argument("--fail-under", type=float, default=0.75)
    harness.add_argument("--format", choices=["markdown", "json"], default="markdown")
    harness.add_argument("--output", type=_path, default=None)
    harness.add_argument(
        "--baseline",
        type=_path,
        default=None,
        help="fail on regression against this committed baseline, not only against the floor",
    )
    harness.add_argument(
        "--update-baseline",
        type=_path,
        default=None,
        help="write this run's scores as the new accepted baseline",
    )
    harness.set_defaults(func=cmd_harness)

    synthesize = sub.add_parser(
        "synthesize",
        help="Fold working spheres into themes above an aggregation floor.",
    )
    synthesize.add_argument("--input", type=_path, default=None, help="JSON bundles from many subjects")
    synthesize.add_argument("--subject-id", default=None)
    synthesize.add_argument("--days", type=int, default=14)
    synthesize.add_argument("--min-subjects", type=int, default=5)
    synthesize.add_argument("--format", choices=["markdown", "json"], default="markdown")
    synthesize.set_defaults(func=cmd_synthesize)

    resume = sub.add_parser(
        "resume-study",
        help="Measure task-resume time from the local trace (docs/VALIDATION.md V2).",
    )
    resume.add_argument("--subject-id", default=None)
    resume.add_argument("--days", type=int, default=14)
    resume.add_argument(
        "--gap-minutes",
        type=float,
        default=15.0,
        help="a pause longer than this counts as an interruption",
    )
    resume.add_argument(
        "--substantive-seconds",
        type=float,
        default=60.0,
        help="a return shorter than this is a glance, not resumed work",
    )
    resume.add_argument(
        "--block-days",
        type=int,
        default=1,
        help="length of each alternating condition block",
    )
    resume.add_argument("--format", choices=["markdown", "json"], default="markdown")
    resume.add_argument("--output", type=_path, default=None)
    resume.set_defaults(func=cmd_resume_study)

    deep = sub.add_parser(
        "deep-harness",
        help="Judgement-based evaluation with deep agents (optional extra, needs an API key).",
    )
    deep.add_argument("--model", default="anthropic:claude-sonnet-4-5")
    deep.add_argument("--prompt", default=None, help="Override the evaluation task.")
    deep.add_argument("--output", type=_path, default=None)
    deep.set_defaults(func=cmd_deep_harness)

    encrypt = sub.add_parser(
        "encrypt-store",
        help="Enable encryption at rest and migrate existing rows (needs the [encrypted] extra).",
    )
    encrypt.add_argument("--status", action="store_true", help="Report state without changing anything.")
    encrypt.set_defaults(func=cmd_encrypt_store)

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
