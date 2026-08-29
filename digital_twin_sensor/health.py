from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from .collectors.macos_active_window import active_window
from .config import load_config
from .fleet import DASHBOARD_SERVICE, SENSOR_SERVICE, _is_running, service_status
from .store import EventStore, parse_dt, utc_now


WATCHDOG_SERVICE = "com.local.digital-twin-watchdog"


def _db_status(db_path: Path) -> dict[str, Any]:
    path = db_path.expanduser()
    exists = path.exists()
    return {
        "name": "Local event store",
        "path": str(path),
        "exists": exists,
        "bytes": int(path.stat().st_size) if exists else 0,
        "status": "ready" if exists else "attention",
        "detail": "local event store is present" if exists else "no event store yet",
    }


def _last_event_summary(db_path: Path, subject_id: str, days: int = 1) -> dict[str, Any]:
    store = EventStore(db_path)
    try:
        events = store.fetch_window(subject_id=subject_id, days=days)
        total = store.count_events(subject_id=subject_id)
    finally:
        store.close()

    if not events:
        return {
            "events_in_window": 0,
            "events_all_time": total,
            "last_event": None,
            "last_age_seconds": None,
            "status": "waiting",
            "detail": "no events in the recent health window",
        }

    last_event = max(events, key=lambda item: item["ts_end"])
    age = max(0, round((utc_now() - parse_dt(last_event["ts_end"])).total_seconds()))
    return {
        "events_in_window": len(events),
        "events_all_time": total,
        "last_event": last_event["ts_end"],
        "last_age_seconds": age,
        "last_app": last_event["app"],
        "last_domain": last_event["domain"],
        "status": "ready" if age <= 180 else "stale",
        "detail": f"last sample {age}s ago",
    }


def _active_window_permission() -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {
            "name": "macOS Accessibility",
            "status": "unsupported",
            "detail": "active-window permission probe is implemented for macOS",
        }
    try:
        app, title = active_window()
    except Exception as exc:
        return {
            "name": "macOS Accessibility",
            "status": "blocked",
            "detail": str(exc),
        }
    return {
        "name": "macOS Accessibility",
        "status": "ready",
        "detail": f"foreground app visible: {app or 'unknown'}",
        "sample_title_visible": bool(title),
    }


def _automation_probe(config: dict[str, Any]) -> dict[str, Any]:
    depth = int(config.get("context_capture_depth", 1))
    browser_min = int(config.get("browser_tab_detail_min_depth", 2))
    ax_min = int(config.get("accessibility_surface_min_depth", 3))
    browser_active = bool(config.get("enable_browser_tab_details", True) and depth >= browser_min)
    ax_active = bool(config.get("enable_accessibility_surface_details", True) and depth >= ax_min)
    targets = []
    if browser_active:
        targets.extend(config.get("browser_tab_detail_apps", []))
    if ax_active:
        targets.extend(config.get("accessibility_surface_detail_apps", []))

    if not targets:
        return {
            "name": "Automation Permissions",
            "status": "ready",
            "detail": "no app-specific automation layer is currently active",
        }
    return {
        "name": "Automation Permissions",
        "status": "attention",
        "detail": "macOS may ask permission the first time these apps are inspected: "
        + ", ".join(str(item) for item in targets),
    }


def _diagnostics(
    *,
    config: dict[str, Any],
    db_path: Path,
    collector: dict[str, Any],
    dashboard: dict[str, Any],
    watchdog: dict[str, Any],
    last_event: dict[str, Any],
    stale_after_seconds: int,
) -> list[dict[str, Any]]:
    last_age = last_event.get("last_age_seconds")
    sensor_ready = _is_running(collector)
    dashboard_ready = _is_running(dashboard)
    watchdog_ready = _is_running(watchdog) or watchdog.get("installed")
    paused = bool(config.get("collection_paused", False))
    fresh = paused or (last_age is not None and int(last_age) <= stale_after_seconds)
    raw_upload = bool(config.get("fleet_raw_event_upload", False))
    browser_paths = bool(config.get("browser_tab_store_url_path", False) or config.get("browser_tab_store_query", False))

    return [
        {
            "name": "Collection mode",
            "status": "attention" if paused else "ready",
            "detail": "collection is paused; services remain available" if paused else "collection is enabled",
        },
        {
            "name": "Collector service",
            "status": "ready" if sensor_ready else "blocked",
            "detail": f"{collector.get('state', 'unknown')} pid={collector.get('pid') or 'none'}",
        },
        {
            "name": "Dashboard service",
            "status": "ready" if dashboard_ready else "blocked",
            "detail": f"{dashboard.get('state', 'unknown')} pid={dashboard.get('pid') or 'none'}",
        },
        {
            "name": "Watchdog service",
            "status": "ready" if watchdog_ready else "attention",
            "detail": "installed" if watchdog_ready else "not installed yet",
        },
        {
            "name": "Sample freshness",
            "status": "ready" if fresh else "attention",
            "detail": "paused intentionally" if paused else last_event.get("detail", "waiting for samples"),
        },
        _active_window_permission(),
        _automation_probe(config),
        {
            "name": "PII masking",
            "status": "ready" if config.get("mask_pii", True) else "blocked",
            "detail": "pre-storage masking enabled" if config.get("mask_pii", True) else "must be enabled before product use",
        },
        {
            "name": "URL minimization",
            "status": "ready" if not browser_paths else "attention",
            "detail": "browser paths/queries redacted" if not browser_paths else "path or query retention is enabled",
        },
        {
            "name": "Raw upload boundary",
            "status": "ready" if not raw_upload else "blocked",
            "detail": "raw event upload disabled" if not raw_upload else "raw event upload should not be product default",
        },
        _db_status(db_path),
    ]


def _beyond_paper() -> list[dict[str, str]]:
    return [
        {
            "name": "Operational sensor",
            "status": "implemented",
            "detail": "continuous local collector, LaunchAgent deployment, dashboard, and local SQLite store",
        },
        {
            "name": "Privacy gate stack",
            "status": "implemented",
            "detail": "pre-storage redaction, URL minimization, raw-upload blocking, and context-pack admission decisions",
        },
        {
            "name": "Living context graph",
            "status": "implemented",
            "detail": "privacy-gated graph of domains, apps, artifacts, tasks, time, and masked private signals",
        },
        {
            "name": "Working spheres",
            "status": "implemented",
            "detail": "activity clustering, resume packs, transition paths, and confidence explanations",
        },
        {
            "name": "Signal depth ladder",
            "status": "implemented",
            "detail": "browser metadata, allowlisted Accessibility metadata, playback visibility, and eye-proxy stance",
        },
        {
            "name": "Fleet posture",
            "status": "implemented",
            "detail": "local endpoint identity, policy posture, connector readiness, and portability model",
        },
    ]


def _paper_deviations() -> list[dict[str, str]]:
    return [
        {
            "name": "Learned filter router",
            "status": "gap",
            "detail": "the paper uses a learned Query x DTS modality router; this prototype uses rule cues plus DTS heuristics",
        },
        {
            "name": "Feedback attribution",
            "status": "gap",
            "detail": "the paper decomposes failures across modality, retrieval, and synthesis; this prototype has no feedback labels yet",
        },
        {
            "name": "Collective signal",
            "status": "gap",
            "detail": "the paper includes collective filters; this local build is single-user until fleet summary sync exists",
        },
        {
            "name": "Evaluation metric",
            "status": "gap",
            "detail": "the paper reports TLR/FLR; this build needs task-resume and answer-quality evaluation",
        },
        {
            "name": "Causality claim",
            "status": "risk",
            "detail": "current attention correlations should be described as evidence, not causal proof, until outcome labels exist",
        },
    ]


def _product_gaps() -> list[dict[str, str]]:
    return [
        {
            "name": "Encrypted storage",
            "status": "next",
            "detail": "add SQLCipher or encrypted event bundles before enterprise deployment",
        },
        {
            "name": "Menubar indicator",
            "status": "next",
            "detail": "always-visible collection state, pause button, and permission alerts",
        },
        {
            "name": "Permission doctor UI",
            "status": "implemented",
            "detail": "dashboard and CLI now expose service, permission, freshness, and privacy diagnostics",
        },
        {
            "name": "Pause/resume and retention",
            "status": "implemented",
            "detail": "dashboard and CLI can pause collection and purge expired local rows without uninstalling services",
        },
        {
            "name": "OCR summary gate",
            "status": "next",
            "detail": "for opaque apps, store only redacted local summaries and discard temporary screenshots",
        },
        {
            "name": "Feedback learning",
            "status": "next",
            "detail": "collect good/bad labels and update filter routing separately from retrieval/synthesis failures",
        },
        {
            "name": "GitLab summary sync",
            "status": "next",
            "detail": "push context packs and health reports, not raw event rows",
        },
    ]


def _research_backlog() -> list[dict[str, str]]:
    return [
        {
            "name": "Evolving context cards",
            "status": "next",
            "detail": "turn repeated working-sphere evidence into living notes with summary, open questions, next actions, sensitivity, expiry, and evidence ids",
            "source": "https://arxiv.org/abs/2510.04618",
        },
        {
            "name": "Memory maintenance loop",
            "status": "next",
            "detail": "add explicit extract, retrieve-route, update, consolidate, forget, and stale-memory diagnostics instead of append-only accumulation",
            "source": "https://arxiv.org/html/2606.24775v1",
        },
        {
            "name": "Dynamic graph evolution",
            "status": "next",
            "detail": "let new events update existing context nodes, strengthen/weaken links, and expose why a relationship changed",
            "source": "https://arxiv.org/html/2502.12110v1",
        },
        {
            "name": "Feedback-labeled evaluation",
            "status": "next",
            "detail": "collect explicit useful/not-useful labels and separate modality-routing, retrieval, and synthesis failures for paper-grade metrics",
            "source": "https://arxiv.org/abs/2605.15505",
        },
        {
            "name": "Offline policy rehearsal",
            "status": "research",
            "detail": "model context-pack decisions as trajectories so future routing policies can be tested before they affect live handoffs",
            "source": "https://arxiv.org/abs/2603.22083",
        },
        {
            "name": "Trust calibration UI",
            "status": "next",
            "detail": "show confidence, evidence gaps, and attribution of errors so the twin is never presented as a faithful copy without proof",
            "source": "https://arxiv.org/abs/2605.19838",
        },
        {
            "name": "Anti-overclaim benchmark",
            "status": "research",
            "detail": "measure individuation, bias, and false confidence before calling the model a reliable personal twin",
            "source": "https://arxiv.org/abs/2509.19088",
        },
        {
            "name": "Event-bus simulator",
            "status": "future",
            "detail": "split the product into user, content, interaction, and platform loops for reproducible counterfactual experiments",
            "source": "https://arxiv.org/abs/2603.11333",
        },
    ]


def build_health_report(
    *,
    db_path: Path,
    config_path: Path,
    stale_after_seconds: int = 180,
) -> dict[str, Any]:
    config = load_config(config_path)
    collector = service_status(SENSOR_SERVICE)
    dashboard = service_status(DASHBOARD_SERVICE)
    watchdog = service_status(WATCHDOG_SERVICE)
    last_event = _last_event_summary(db_path, config["subject_id"])
    diagnostics = _diagnostics(
        config=config,
        db_path=db_path,
        collector=collector,
        dashboard=dashboard,
        watchdog=watchdog,
        last_event=last_event,
        stale_after_seconds=stale_after_seconds,
    )
    blocked = sum(1 for item in diagnostics if item.get("status") == "blocked")
    attention = sum(1 for item in diagnostics if item.get("status") == "attention")
    ready = sum(1 for item in diagnostics if item.get("status") == "ready")
    if blocked:
        posture = "blocked"
    elif attention:
        posture = "attention"
    else:
        posture = "ready"

    return {
        "status": posture,
        "generated_at": utc_now().isoformat(),
        "stale_after_seconds": stale_after_seconds,
        "summary": {
            "ready": ready,
            "attention": attention,
            "blocked": blocked,
            "sample_interval_seconds": int(config.get("sample_interval_seconds", 15)),
            "capture_depth": int(config.get("context_capture_depth", 1)),
        },
        "services": {
            "collector": collector,
            "dashboard": dashboard,
            "watchdog": watchdog,
        },
        "last_event": last_event,
        "diagnostics": diagnostics,
        "beyond_paper": _beyond_paper(),
        "paper_deviations": _paper_deviations(),
        "product_gaps": _product_gaps(),
        "research_backlog": _research_backlog(),
    }


def kickstart_service(label: str) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {"service": label, "status": "unsupported", "detail": "launchctl is macOS-only"}
    result = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=8,
    )
    return {
        "service": label,
        "status": "restarted" if result.returncode == 0 else "failed",
        "detail": (result.stderr or result.stdout).strip(),
    }


def run_watchdog(
    *,
    db_path: Path,
    config_path: Path,
    stale_after_seconds: int = 180,
    fix: bool = False,
) -> dict[str, Any]:
    report = build_health_report(
        db_path=db_path,
        config_path=config_path,
        stale_after_seconds=stale_after_seconds,
    )
    actions = []
    services = report["services"]
    last_age = report["last_event"].get("last_age_seconds")

    if fix and not _is_running(services["collector"]):
        actions.append(kickstart_service(SENSOR_SERVICE))
    if fix and not _is_running(services["dashboard"]):
        actions.append(kickstart_service(DASHBOARD_SERVICE))
    if fix and last_age is not None and int(last_age) > stale_after_seconds:
        actions.append(kickstart_service(SENSOR_SERVICE))

    if actions:
        report = build_health_report(
            db_path=db_path,
            config_path=config_path,
            stale_after_seconds=stale_after_seconds,
        )

    return {
        "fixed": bool(actions),
        "actions": actions,
        "report": report,
    }


def format_health_report(report: dict[str, Any]) -> str:
    lines = [
        f"Digital Twin Product Doctor: {report.get('status', 'unknown')}",
        f"Generated: {report.get('generated_at', '')}",
        "",
        "Diagnostics:",
    ]
    for item in report.get("diagnostics", []):
        lines.append(f"- {item.get('status', 'unknown')}: {item.get('name', '')} - {item.get('detail', '')}")

    lines.append("")
    lines.append("Paper deviations:")
    for item in report.get("paper_deviations", []):
        lines.append(f"- {item.get('status', 'gap')}: {item.get('name', '')} - {item.get('detail', '')}")

    lines.append("")
    lines.append("Product gaps:")
    for item in report.get("product_gaps", []):
        lines.append(f"- {item.get('status', 'next')}: {item.get('name', '')} - {item.get('detail', '')}")

    lines.append("")
    lines.append("Research backlog:")
    for item in report.get("research_backlog", []):
        lines.append(f"- {item.get('status', 'next')}: {item.get('name', '')} - {item.get('detail', '')}")

    return "\n".join(lines)
