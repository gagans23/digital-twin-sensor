from __future__ import annotations

import hashlib
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .store import parse_dt, utc_now


SENSOR_SERVICE = "com.local.digital-twin-sensor"
DASHBOARD_SERVICE = "com.local.digital-twin-dashboard"


def default_device_id() -> str:
    seed = "|".join(
        [
            socket.gethostname(),
            platform.system(),
            platform.machine(),
            str(os.getuid()) if hasattr(os, "getuid") else "user",
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"device_{digest}"


def default_device_name() -> str:
    hostname = socket.gethostname().split(".", 1)[0].strip()
    return hostname or f"{platform.system()} endpoint"


def service_status(label: str) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {
            "installed": False,
            "state": "unsupported",
            "detail": "service inspection is implemented for macOS LaunchAgents in this starter",
        }

    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception as exc:
        return {"installed": False, "state": "unknown", "detail": str(exc)}

    if result.returncode != 0:
        return {"installed": False, "state": "not installed", "detail": result.stderr.strip()}

    state = "unknown"
    pid = None
    last_exit = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("state = "):
            state = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("pid = "):
            pid = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("last exit code = "):
            last_exit = stripped.split("=", 1)[1].strip()

    return {
        "installed": True,
        "state": state,
        "pid": pid,
        "last_exit_code": last_exit,
    }


def _is_running(status: dict[str, Any]) -> bool:
    return bool(status.get("installed")) and str(status.get("state")) in {"active", "running"}


def _last_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    return max(events, key=lambda item: item["ts_start"])


def _policy(config: dict[str, Any]) -> dict[str, Any]:
    depth = int(config.get("context_capture_depth", 1))
    browser_depth = int(config.get("browser_tab_detail_min_depth", 2))
    return {
        "name": config.get("fleet_policy_name", "Local Enterprise Baseline"),
        "version": config.get("fleet_policy_version", "local-dev"),
        "capture_depth": depth,
        "retention_days": int(config.get("retention_days", 30)),
        "mask_pii": bool(config.get("mask_pii", True)),
        "redact_url_paths": bool(config.get("redact_url_paths", True)),
        "browser_tab_details": bool(
            config.get("enable_browser_tab_details", True) and depth >= browser_depth
        ),
        "browser_url_path": bool(config.get("browser_tab_store_url_path", False)),
        "browser_url_query": bool(config.get("browser_tab_store_query", False)),
        "working_spheres": bool(config.get("enable_working_spheres", True)),
        "context_graph": bool(config.get("enable_context_graph", True)),
        "raw_event_upload": bool(config.get("fleet_raw_event_upload", False)),
        "upload_mode": config.get("fleet_upload_mode", "summaries_only"),
        "allowed_export_targets": list(config.get("fleet_allowed_export_targets", [])),
    }


def _connectors(config: dict[str, Any]) -> list[dict[str, Any]]:
    depth = int(config.get("context_capture_depth", 1))
    browser_depth = int(config.get("browser_tab_detail_min_depth", 2))
    return [
        {
            "name": "macOS Active Window",
            "status": "enabled",
            "depth": "Depth 1",
            "scope": "foreground app, redacted title, dwell, domain",
            "sync_policy": "local events, summaries only",
        },
        {
            "name": "Safari / Chrome Tab Metadata",
            "status": "enabled" if config.get("enable_browser_tab_details", True) and depth >= browser_depth else "ready",
            "depth": f"Depth {browser_depth}",
            "scope": "redacted tab title, URL domain, sanitized URL",
            "sync_policy": "paths and queries redacted by default",
        },
        {
            "name": "Working Spheres",
            "status": "enabled" if config.get("enable_working_spheres", True) else "disabled",
            "depth": "Derived",
            "scope": "activity clusters, returns, resume packs",
            "sync_policy": "safe summary candidate",
        },
        {
            "name": "Context Graph",
            "status": "enabled" if config.get("enable_context_graph", True) else "disabled",
            "depth": "Derived",
            "scope": "domain, app, artifact, task, time, privacy nodes",
            "sync_policy": "safe summary candidate",
        },
        {
            "name": "Opaque App Deep Detail",
            "status": "planned",
            "depth": "Depth 2/3 opt-in",
            "scope": "per-app Accessibility text or local OCR summary",
            "sync_policy": "never raw screenshots by default",
        },
    ]


def _sync_readiness(config: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, str]]:
    control_plane_url = str(config.get("fleet_control_plane_url", "")).strip()
    sync_enabled = bool(config.get("fleet_sync_enabled", False))
    raw_upload = bool(policy.get("raw_event_upload", False))
    browser_paths = bool(policy.get("browser_url_path", False) or policy.get("browser_url_query", False))

    items = [
        {
            "name": "Device identity",
            "status": "ready" if config.get("fleet_device_id") else "attention",
            "detail": "stable local device id is present" if config.get("fleet_device_id") else "device id is missing",
        },
        {
            "name": "Local redaction",
            "status": "ready" if policy["mask_pii"] else "blocked",
            "detail": "PII masking is on" if policy["mask_pii"] else "PII masking must be enabled before enterprise sync",
        },
        {
            "name": "Raw event upload",
            "status": "ready" if not raw_upload else "blocked",
            "detail": "raw events are not uploadable by policy" if not raw_upload else "raw upload should stay off for enterprise baseline",
        },
        {
            "name": "Browser URL minimization",
            "status": "ready" if not browser_paths else "attention",
            "detail": "URL paths and queries are redacted" if not browser_paths else "URL paths or queries are being retained",
        },
        {
            "name": "Control plane",
            "status": "ready" if sync_enabled and control_plane_url else "not enrolled",
            "detail": control_plane_url or "no remote control plane configured yet",
        },
        {
            "name": "Encryption at rest",
            "status": "planned",
            "detail": "SQLite encryption is not implemented in this starter yet",
        },
        {
            "name": "Signed updates",
            "status": "planned",
            "detail": "portable installers need package signing before broad deployment",
        },
    ]
    return items


def _health(collector: dict[str, Any], dashboard: dict[str, Any], last_age_seconds: int | None) -> str:
    if not _is_running(collector):
        return "offline"
    if last_age_seconds is None:
        return "waiting"
    if last_age_seconds > 180:
        return "stale"
    if not _is_running(dashboard):
        return "collector-only"
    return "online"


def _db_bytes(db_path: Path) -> int:
    try:
        return int(db_path.expanduser().stat().st_size)
    except OSError:
        return 0


def _portability() -> list[dict[str, str]]:
    return [
        {
            "name": "macOS agent",
            "status": "implemented",
            "detail": "LaunchAgent keeps collector and dashboard running at login",
        },
        {
            "name": "Windows service",
            "status": "planned",
            "detail": "package as signed MSI with Windows Service and browser connector",
        },
        {
            "name": "Linux service",
            "status": "planned",
            "detail": "package as deb/rpm with systemd user service",
        },
        {
            "name": "MDM deployment",
            "status": "planned",
            "detail": "Jamf, Intune, Kandji, or fleet scripts should install policy and permissions",
        },
        {
            "name": "Control plane",
            "status": "planned",
            "detail": "central device registry, policy assignment, summaries sync, audit log",
        },
    ]


def _admin_actions(config: dict[str, Any]) -> list[dict[str, str]]:
    control_plane_url = str(config.get("fleet_control_plane_url", "")).strip()
    return [
        {
            "name": "Enroll endpoint",
            "status": "ready" if control_plane_url else "next",
            "detail": "store a control-plane URL and enrollment fingerprint, then enable summary sync",
        },
        {
            "name": "Assign policy",
            "status": "local",
            "detail": "current machine follows the local enterprise baseline config",
        },
        {
            "name": "Export context pack",
            "status": "next",
            "detail": "create safe Kiro/Codex/GitLab handoff packages from working spheres",
        },
        {
            "name": "Rotate device token",
            "status": "planned",
            "detail": "requires remote enrollment service",
        },
    ]


def build_fleet_status(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    db_path: Path,
    days: int,
    total_count: int,
    collector_status: dict[str, Any] | None = None,
    dashboard_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collector = collector_status or service_status(SENSOR_SERVICE)
    dashboard = dashboard_status or service_status(DASHBOARD_SERVICE)
    last_event = _last_event(events)
    last_age_seconds = None
    if last_event:
        last_age_seconds = max(0, round((utc_now() - parse_dt(last_event["ts_end"])).total_seconds()))

    policy = _policy(config)
    health = _health(collector, dashboard, last_age_seconds)
    enrolled = bool(config.get("fleet_sync_enabled") and config.get("fleet_control_plane_url"))
    readiness = _sync_readiness(config, policy)

    device = {
        "id": config.get("fleet_device_id") or default_device_id(),
        "name": config.get("fleet_device_name") or default_device_name(),
        "health": health,
        "enrolled": enrolled,
        "os": platform.system(),
        "os_version": platform.mac_ver()[0] if platform.system() == "Darwin" else platform.release(),
        "architecture": platform.machine(),
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "agent_version": __version__,
        "policy_version": policy["version"],
        "capture_depth": policy["capture_depth"],
        "events_in_window": len(events),
        "events_all_time": total_count,
        "last_event": last_event["ts_end"] if last_event else None,
        "last_age_seconds": last_age_seconds,
        "db_path": str(db_path.expanduser()),
        "db_bytes": _db_bytes(db_path),
        "collector": collector,
        "dashboard": dashboard,
    }

    ready_count = sum(1 for item in readiness if item["status"] == "ready")
    blocking_count = sum(1 for item in readiness if item["status"] == "blocked")
    return {
        "status": "enrolled" if enrolled else "local-only",
        "generated_at": utc_now().isoformat(),
        "days": days,
        "summary": {
            "device_count": 1,
            "online_count": 1 if health in {"online", "collector-only"} else 0,
            "enrolled_count": 1 if enrolled else 0,
            "policy_version": policy["version"],
            "sync_mode": config.get("fleet_upload_mode", "summaries_only") if enrolled else "local_only",
            "readiness_ready": ready_count,
            "readiness_total": len(readiness),
            "blocking_count": blocking_count,
        },
        "devices": [device],
        "active_policy": policy,
        "connectors": _connectors(config),
        "sync_readiness": readiness,
        "portability": _portability(),
        "admin_actions": _admin_actions(config),
    }
