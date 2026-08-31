from __future__ import annotations

import json
import mimetypes
import socket
import secrets
import urllib.parse
import webbrowser
from collections import Counter, defaultdict
from datetime import timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

from .collectors.local_ocr import ocr_provider_status
from .connectors import registry_summary
from .collectors.macos_active_window import build_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ensure_config, load_config, write_config
from .context_graph import build_context_graph
from .context_pack import build_context_pack
from .fleet import DASHBOARD_SERVICE, SENSOR_SERVICE, build_fleet_status, service_status
from .health import build_health_report, run_watchdog
from .learning import LearningStore, build_learning_state
from .query import retrieve
from .resume import ResumeConflict, build_resume_view, resume_action
from .store import open_event_store, parse_dt, utc_now
from .twin import build_digital_twin_signature
from .working_spheres import build_working_spheres


def _safe_int(value: str | None, default: int, minimum: int = 1, maximum: int = 365) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, min(maximum, parsed))


def _seconds_to_hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def _serialize_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "subject_id": event["subject_id"],
        "source": event["source"],
        "app": event["app"],
        "title": event["title"],
        "artifact": event["artifact"],
        "domain": event["domain"],
        "action": event["action"],
        "ts_start": event["ts_start"],
        "ts_end": event["ts_end"],
        "dwell_seconds": round(float(event["dwell_seconds"]), 2),
        "metadata": event.get("metadata", {}),
    }


def _daily_activity(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    days: dict[str, float] = defaultdict(float)
    for event in events:
        day = parse_dt(event["ts_start"]).date().isoformat()
        days[day] += float(event["dwell_seconds"])
    return [
        {"day": day, "dwell_seconds": round(seconds, 2), "hours": _seconds_to_hours(seconds)}
        for day, seconds in sorted(days.items())
    ]


def _hourly_heatmap(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hours: dict[int, float] = defaultdict(float)
    for event in events:
        hour = parse_dt(event["ts_start"]).hour
        hours[hour] += float(event["dwell_seconds"])
    peak = max(hours.values()) if hours else 1.0
    return [
        {
            "hour": hour,
            "label": f"{hour:02d}:00",
            "dwell_seconds": round(hours.get(hour, 0.0), 2),
            "intensity": round(hours.get(hour, 0.0) / peak, 4) if peak else 0,
        }
        for hour in range(24)
    ]


def _domain_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dwell: dict[str, float] = defaultdict(float)
    visits: Counter[str] = Counter()
    apps_by_domain: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        domain = event["domain"]
        dwell[domain] += float(event["dwell_seconds"])
        visits[domain] += 1
        apps_by_domain[domain][event["app"]] += 1
    total = sum(dwell.values()) or 1.0
    return [
        {
            "domain": domain,
            "dwell_seconds": round(seconds, 2),
            "hours": _seconds_to_hours(seconds),
            "share": round(seconds / total, 4),
            "events": visits[domain],
            "top_apps": apps_by_domain[domain].most_common(4),
        }
        for domain, seconds in sorted(dwell.items(), key=lambda item: item[1], reverse=True)
    ]


def _top_items(events: list[dict[str, Any]], key: str, limit: int = 10) -> list[dict[str, Any]]:
    dwell: dict[str, float] = defaultdict(float)
    visits: Counter[str] = Counter()
    domains: dict[str, str] = {}
    for event in events:
        label = event[key]
        dwell[label] += float(event["dwell_seconds"])
        visits[label] += 1
        domains.setdefault(label, event["domain"])
    return [
        {
            "name": name,
            "domain": domains.get(name, "other"),
            "dwell_seconds": round(seconds, 2),
            "hours": _seconds_to_hours(seconds),
            "visits": visits[name],
        }
        for name, seconds in sorted(dwell.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _surface_details(events: list[dict[str, Any]], config: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    by_app: dict[str, dict[str, Any]] = {}
    browser_apps = {str(item).lower() for item in config.get("browser_tab_detail_apps", [])}
    accessibility_apps = {str(item).lower() for item in config.get("accessibility_surface_detail_apps", [])}
    ocr_apps = {str(item).lower() for item in config.get("ocr_surface_detail_apps", [])}
    depth = int(config.get("context_capture_depth", 1))
    browser_min_depth = int(config.get("browser_tab_detail_min_depth", 2))
    accessibility_min_depth = int(config.get("accessibility_surface_min_depth", 3))
    ocr_min_depth = int(config.get("ocr_surface_min_depth", 4))

    for event in events:
        if event.get("domain") == "system" or event.get("action") == "system":
            continue
        app = event["app"]
        item = by_app.setdefault(
            app,
            {
                "app": app,
                "events": 0,
                "dwell_seconds": 0.0,
                "domains": Counter(),
                "artifacts": Counter(),
                "browser_domains": Counter(),
                "surface_detail_events": 0,
                "latest_detail": None,
                "last_seen": None,
            },
        )
        item["events"] += 1
        item["dwell_seconds"] += float(event["dwell_seconds"])
        item["domains"][event["domain"]] += 1
        item["artifacts"][event["artifact"]] += 1
        item["last_seen"] = event["ts_end"]
        surface_detail = event.get("metadata", {}).get("surface_detail")
        if isinstance(surface_detail, dict) and surface_detail.get("status") == "captured":
            item["surface_detail_events"] += 1
            item["latest_detail"] = surface_detail
            if surface_detail.get("url_domain"):
                item["browser_domains"][surface_detail["url_domain"]] += 1

    cards = []
    for item in sorted(by_app.values(), key=lambda value: value["dwell_seconds"], reverse=True)[:limit]:
        app = item["app"]
        app_key = app.lower()
        latest_detail = item["latest_detail"] or {}
        top_artifacts = [
            {"name": name, "events": int(count)}
            for name, count in item["artifacts"].most_common(4)
        ]
        known_fields = ["app", "window title", "dwell time", "domain", "switch sequence"]
        status = "window metadata"
        detail_level = "Depth 1"
        what_we_know = "The sensor can see the app, redacted window title, dwell time, domain, and switching pattern."
        how_to_deepen = "Add an app-specific connector only if it can expose useful metadata without reading private content."
        privacy_boundary = "No screenshots, keystrokes, clipboard, microphone, or document bodies."

        if item["surface_detail_events"]:
            if latest_detail.get("kind") == "accessibility_snapshot":
                status = "in-app surface captured"
                detail_level = "Depth 3 UI metadata"
                known_fields = ["UI roles", "redacted visible labels", "dwell time", "switch sequence"]
                roles = ", ".join(item["role"] for item in latest_detail.get("roles", [])[:3]) or "UI elements"
                what_we_know = f"Accessibility exposed {latest_detail.get('element_count', 0)} UI elements; strongest roles are {roles}."
                how_to_deepen = "If playback title/channel is still absent, add an app-specific connector or local OCR summary gate."
                privacy_boundary = latest_detail.get("privacy", privacy_boundary)
            elif latest_detail.get("kind") == "ocr_summary":
                status = "ocr summary captured"
                detail_level = "Depth 4 local OCR"
                known_fields = ["redacted OCR hints", "local OCR confidence", "dwell time", "switch sequence"]
                provider = latest_detail.get("provider", "local OCR")
                confidence = round(float(latest_detail.get("confidence", 0.0)) * 100)
                what_we_know = f"{provider} read {latest_detail.get('line_count', 0)} visible text lines with about {confidence}% average confidence."
                how_to_deepen = "Prefer an app-specific connector for structured playback state; keep OCR as summary-only fallback."
                privacy_boundary = latest_detail.get("privacy", privacy_boundary)
            else:
                status = "browser detail captured"
                detail_level = "Depth 2 metadata"
                known_fields = ["tab title", "URL domain", "sanitized URL", "dwell time", "switch sequence"]
                domain = latest_detail.get("url_domain") or "unknown domain"
                what_we_know = f"The active tab metadata is captured for {domain}; URL paths and queries are redacted by default."
                how_to_deepen = "Optional next step: store URL paths for selected domains only, still stripping query strings and fragments."
                privacy_boundary = latest_detail.get("privacy", privacy_boundary)
        elif app_key in browser_apps:
            status = "browser detail available"
            detail_level = f"Depth {browser_min_depth} ready" if depth < browser_min_depth else "waiting for tab sample"
            known_fields = ["app", "window title", "dwell time", "domain"]
            if depth < browser_min_depth:
                what_we_know = f"Browser tab detail is configured for {app}, but capture depth is {depth}; it activates at Depth {browser_min_depth}."
                how_to_deepen = f"Set context_capture_depth to {browser_min_depth} to capture redacted tab title and sanitized URL domain."
            else:
                what_we_know = f"{app} is eligible for tab detail. The next frontmost sample should include tab title and sanitized URL metadata."
                how_to_deepen = "Keep Safari/Chrome frontmost for a sample interval, then refresh this dashboard."
            privacy_boundary = "URL path, query, fragment, usernames, passwords, and PII are redacted before storage."
        elif app_key in accessibility_apps:
            status = "in-app detail available"
            detail_level = f"Depth {accessibility_min_depth} gated" if depth < accessibility_min_depth else "waiting for UI sample"
            known_fields = ["app", "window title", "dwell time", "domain"]
            if depth < accessibility_min_depth:
                what_we_know = f"{app} is allowlisted for Accessibility metadata, but capture depth is {depth}; it activates at Depth {accessibility_min_depth}."
                how_to_deepen = f"Set context_capture_depth to {accessibility_min_depth} to capture redacted UI labels exposed by this app."
            else:
                what_we_know = f"{app} is eligible for an allowlisted Accessibility snapshot. The next frontmost sample may include visible UI labels."
                how_to_deepen = "Keep the app frontmost for a sample interval. If no labels appear, build an app-specific connector or OCR summary gate."
            privacy_boundary = "Only redacted UI labels and roles are stored; no screenshots, keystrokes, clipboard, or camera."
        elif app_key in ocr_apps:
            provider = ocr_provider_status(config)
            status = "ocr summary available"
            detail_level = f"Depth {ocr_min_depth} gated" if depth < ocr_min_depth else "waiting for OCR sample"
            known_fields = ["app", "window title", "dwell time", "domain"]
            if depth < ocr_min_depth:
                what_we_know = f"{app} is allowlisted for local OCR summaries, but capture depth is {depth}; it activates at Depth {ocr_min_depth}."
                how_to_deepen = f"Set context_capture_depth to {ocr_min_depth} to run local OCR when browser and Accessibility metadata are empty."
            elif provider.get("status") != "ready":
                what_we_know = f"{app} is OCR-allowlisted, but no local OCR provider is ready."
                how_to_deepen = "Install the macOS Vision helper through scripts/install_launch_agent.sh or install Tesseract for fallback readiness."
            else:
                what_we_know = f"{app} is eligible for local OCR summaries. The next frontmost sample may include redacted text hints."
                how_to_deepen = "Keep the app frontmost for a sample interval, then inspect the Signal Depth and Learning Mode tabs."
            privacy_boundary = "Window pixels are transient; only redacted OCR hints and summary are stored."
        elif "ibo pro player" in app_key:
            status = "opaque app"
            detail_level = "Depth 1 only"
            what_we_know = "macOS is exposing the app/window surface, but not the in-app playback/channel/content details."
            how_to_deepen = "Use a per-app allowlist for Accessibility text first. If that is empty, use local OCR summaries of the window without storing screenshots."
            privacy_boundary = "Do not enable keystrokes, clipboard, raw screenshots, microphone, or automatic cloud upload for this app."

        cards.append(
            {
                "app": app,
                "status": status,
                "detail_level": detail_level,
                "events": int(item["events"]),
                "surface_detail_events": int(item["surface_detail_events"]),
                "dwell_seconds": round(item["dwell_seconds"], 2),
                "hours": _seconds_to_hours(item["dwell_seconds"]),
                "domain": item["domains"].most_common(1)[0][0] if item["domains"] else "other",
                "last_seen": item["last_seen"],
                "known_fields": known_fields,
                "top_artifacts": top_artifacts,
                "browser_domains": [
                    {"domain": name, "events": int(count)}
                    for name, count in item["browser_domains"].most_common(4)
                ],
                "what_we_know": what_we_know,
                "how_to_deepen": how_to_deepen,
                "privacy_boundary": privacy_boundary,
            }
        )

    return cards


def _transitions(events: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    previous = None
    for event in sorted(events, key=lambda item: item["ts_start"]):
        current = event["domain"]
        if previous and previous != current:
            counter[f"{previous} -> {current}"] += 1
        previous = current
    return [{"transition": name, "count": count} for name, count in counter.most_common(limit)]


def _redaction_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    summary: Counter[str] = Counter()
    for event in events:
        findings = event.get("metadata", {}).get("redaction_findings", {})
        if not isinstance(findings, dict):
            continue
        for key, value in findings.items():
            try:
                summary[str(key)] += int(value)
            except (TypeError, ValueError):
                continue
    return dict(sorted(summary.items()))


def _interpret(profile: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not events:
        return [
            {
                "title": "No signal yet",
                "body": "Start the sensor and let it collect a few hours of active-window attention.",
                "tone": "neutral",
            }
        ]

    domain_dist = profile.get("v_dom", {}).get("distribution", {})
    top_domain, top_share = ("unknown", 0.0)
    if domain_dist:
        top_domain, top_share = max(domain_dist.items(), key=lambda item: item[1])

    revisit_rate = profile.get("v_rhythm", {}).get("revisit_rate", 0.0)
    divergence = profile.get("v_div", {}).get("kl_short_vs_long", 0.0)
    likely_domains = profile.get("v_resp", {}).get("likely_owned_domains", [])

    insights = [
        {
            "title": "Primary focus",
            "body": f"{top_domain} is currently the strongest attention domain at {round(top_share * 100)} percent of dwell time.",
            "tone": "focus",
        }
    ]

    if revisit_rate >= 0.2:
        insights.append(
            {
                "title": "Repeated pull",
                "body": "Several artifacts are pulling repeat visits. Use the Evidence view with a recurrent query to see them.",
                "tone": "signal",
            }
        )
    else:
        insights.append(
            {
                "title": "Low revisit pattern",
                "body": "Recent work looks more exploratory than repetitive based on revisit rate.",
                "tone": "neutral",
            }
        )

    if divergence >= 0.2:
        insights.append(
            {
                "title": "Baseline shift",
                "body": "Recent attention has moved away from the longer-window baseline, so differential queries may be useful.",
                "tone": "alert",
            }
        )
    else:
        insights.append(
            {
                "title": "Stable rhythm",
                "body": "Short-window behavior is close to the current baseline.",
                "tone": "steady",
            }
        )

    if likely_domains:
        owned = ", ".join(item["domain"] for item in likely_domains[:3])
        insights.append(
            {
                "title": "Inferred responsibility",
                "body": f"The twin currently infers ownership around: {owned}.",
                "tone": "focus",
            }
        )

    return insights


def _surface_detail_kind(event: dict[str, Any]) -> str:
    detail = event.get("metadata", {}).get("surface_detail")
    if isinstance(detail, dict):
        return str(detail.get("kind", ""))
    return ""


def _is_media_surface(app: str, title: str, detail: dict[str, Any] | None = None) -> bool:
    detail = detail or {}
    haystack = " ".join(
        [
            app,
            title,
            str(detail.get("url_domain", "")),
            " ".join(str(item) for item in detail.get("text_hints", [])[:4]),
        ]
    ).lower()
    media_terms = [
        "player",
        "music",
        "spotify",
        "youtube",
        "twitch",
        "netflix",
        "hulu",
        "video",
        "stream",
        "tv",
        "podcast",
        "radio",
    ]
    return any(term in haystack for term in media_terms)


def _media_focus_payload(events: list[dict[str, Any]]) -> dict[str, Any]:
    recent = sorted(events, key=lambda item: item["ts_start"], reverse=True)
    media_events = []
    for event in recent:
        detail = event.get("metadata", {}).get("surface_detail")
        if not isinstance(detail, dict):
            detail = {}
        if _is_media_surface(event.get("app", ""), event.get("artifact", ""), detail):
            media_events.append(event)

    focus = media_events[0] if media_events else (recent[0] if recent else None)
    if not focus:
        return {
            "status": "empty",
            "current_app": "none",
            "what_we_know": "No recent media or app-focus signal in this window.",
            "playback_visibility": "none",
            "evidence": [],
            "next_step": "Let the collector run while the player or browser is frontmost.",
        }

    detail = focus.get("metadata", {}).get("surface_detail")
    if not isinstance(detail, dict):
        detail = {}
    kind = str(detail.get("kind", ""))
    app = str(focus.get("app", "unknown"))
    evidence = [
        {"label": "app", "value": app},
        {"label": "window", "value": str(focus.get("artifact", ""))[:160]},
        {"label": "domain", "value": str(focus.get("domain", "other"))},
    ]
    if detail.get("url_domain"):
        evidence.append({"label": "url domain", "value": str(detail.get("url_domain"))})
    if detail.get("text_hints"):
        evidence.append({"label": "visible hints", "value": ", ".join(str(item) for item in detail["text_hints"][:3])})
    if detail.get("summary"):
        evidence.append({"label": "ocr summary", "value": str(detail.get("summary"))[:180]})

    if kind == "browser_tab":
        status = "captured"
        playback_visibility = "browser tab metadata"
        what_we_know = "The twin can see the active browser tab title, URL domain, dwell time, and switch sequence."
        next_step = "For richer playback state, add a site-specific connector that stores page-level media metadata without query strings."
    elif kind == "accessibility_snapshot":
        status = "captured"
        playback_visibility = "allowlisted UI metadata"
        what_we_know = "The twin can see redacted Accessibility labels exposed by the player window, plus dwell time and switch sequence."
        next_step = "If the program or channel is still missing, add an app-specific connector or a local OCR summary gate."
    elif kind == "ocr_summary":
        status = "captured"
        playback_visibility = "local OCR summary"
        what_we_know = "The twin can see redacted on-device OCR hints from the visible player window, plus dwell time and switch sequence."
        next_step = "Use OCR labels to learn what was useful, then replace OCR with a structured app connector when possible."
    elif _is_media_surface(app, str(focus.get("artifact", "")), detail):
        status = "opaque"
        playback_visibility = "app/window only"
        what_we_know = "The twin can see that this player has attention, but not the exact channel, stream, or playback state yet."
        next_step = "Enable Depth 3 Accessibility first; if it stays opaque, enable Depth 4 local OCR summaries for this app."
    else:
        status = "watching"
        playback_visibility = "attention only"
        what_we_know = "The latest focus is not clearly a media surface; the twin is tracking app attention and dwell."
        next_step = "Open the player or media tab frontmost and let one sample interval pass."

    return {
        "status": status,
        "current_app": app,
        "current_artifact": str(focus.get("artifact", ""))[:160],
        "last_seen": focus.get("ts_end"),
        "playback_visibility": playback_visibility,
        "what_we_know": what_we_know,
        "evidence": evidence,
        "next_step": next_step,
    }


def _attention_depth_payload(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    surface_details: list[dict[str, Any]],
) -> dict[str, Any]:
    depth = int(config.get("context_capture_depth", 1))
    browser_min = int(config.get("browser_tab_detail_min_depth", 2))
    ax_min = int(config.get("accessibility_surface_min_depth", 3))
    ocr_min = int(config.get("ocr_surface_min_depth", 4))
    browser_active = bool(config.get("enable_browser_tab_details", True) and depth >= browser_min)
    ax_active = bool(config.get("enable_accessibility_surface_details", True) and depth >= ax_min)
    ocr_active = bool(config.get("enable_ocr_surface_details", True) and depth >= ocr_min)
    recent = sorted(events, key=lambda item: item["ts_start"], reverse=True)
    latest = recent[0] if recent else {}

    app_attention = []
    for item in surface_details[:8]:
        events_count = max(int(item.get("events", 0)), 1)
        detail_events = int(item.get("surface_detail_events", 0))
        coverage = round(detail_events / events_count, 3)
        if item.get("status") in {"browser detail captured", "in-app surface captured", "ocr summary captured"}:
            depth_status = "rich"
        elif "available" in str(item.get("status", "")):
            depth_status = "ready"
        elif item.get("status") == "opaque app":
            depth_status = "opaque"
        else:
            depth_status = "basic"
        app_attention.append(
            {
                "app": item.get("app", "unknown"),
                "status": depth_status,
                "detail_level": item.get("detail_level", "Depth 1"),
                "events": int(item.get("events", 0)),
                "hours": item.get("hours", 0),
                "detail_coverage": coverage,
                "what_we_know": item.get("what_we_know", ""),
                "next_step": item.get("how_to_deepen", ""),
            }
        )

    browser_apps = ", ".join(config.get("browser_tab_detail_apps", []))
    ax_apps = ", ".join(config.get("accessibility_surface_detail_apps", []))
    ocr_apps = ", ".join(config.get("ocr_surface_detail_apps", []))
    ocr_status = ocr_provider_status(config)
    ladder = [
        {
            "level": "Depth 1",
            "name": "Foreground attention",
            "status": "active" if depth >= 1 else "off",
            "captures": "front app, redacted title, dwell, sequence, domain",
            "privacy_gate": "no keystrokes, screenshots, clipboard, microphone, or camera",
        },
        {
            "level": "Depth 2",
            "name": "Browser and media metadata",
            "status": "active" if browser_active else "ready" if config.get("enable_browser_tab_details", True) else "off",
            "captures": f"redacted tab title and URL domain for {browser_apps or 'configured browsers'}",
            "privacy_gate": "URL path, query, fragment, usernames, and passwords redacted by default",
        },
        {
            "level": "Depth 3",
            "name": "Allowlisted in-app surface",
            "status": "active" if ax_active else "gated",
            "captures": f"redacted Accessibility labels for {ax_apps or 'allowlisted apps'}",
            "privacy_gate": "metadata only; no raw screenshots or document bodies",
        },
        {
            "level": "Depth 4",
            "name": "Local OCR summaries",
            "status": "active" if ocr_active else "gated",
            "captures": f"short on-device text hints for {ocr_apps or 'allowlisted opaque apps'} when Accessibility exposes nothing",
            "privacy_gate": "no image storage; summaries pass through the same PII mask",
        },
        {
            "level": "Depth 5",
            "name": "Cursor and scroll attention proxy",
            "status": "planned" if not config.get("eye_proxy_collect_cursor", False) else "active",
            "captures": "aggregate regions, hover dwell, scroll velocity, idle/return moments",
            "privacy_gate": "zones and timing only; no typed text or clipboard",
        },
        {
            "level": "Depth 6",
            "name": "Explicit gaze instrumentation",
            "status": "off" if not config.get("eye_proxy_collect_camera_gaze", False) else "active",
            "captures": "calibrated gaze heatmaps from webcam or eye tracker",
            "privacy_gate": "explicit opt-in; local-only derived heatmap; no raw camera frames",
        },
    ]

    media_focus = _media_focus_payload(events)
    recommendations = []
    opaque_apps = [item for item in app_attention if item["status"] == "opaque"]
    if opaque_apps or media_focus.get("status") == "opaque":
        app_name = opaque_apps[0]["app"] if opaque_apps else media_focus.get("current_app", "this app")
        recommendations.append(
            {
                "name": "Deepen opaque player apps",
                "status": "next",
                "detail": f"Start with {app_name}: enable Depth 3 Accessibility, then Depth 4 OCR if the surface remains opaque.",
                "command": f"digital-twin-sensor configure --depth 4 --accessibility-surface-details on --accessibility-app \"{app_name}\" --ocr-surface-details on --ocr-app \"{app_name}\"",
            }
        )
    if not browser_active:
        recommendations.append(
            {
                "name": "Turn on browser context",
                "status": "ready",
                "detail": "Depth 2 gives Safari/Chrome tab titles and URL domains while keeping paths and queries redacted.",
                "command": "digital-twin-sensor configure --depth 2 --browser-tab-details on --browser-url-path off --browser-url-query off",
            }
        )
    recommendations.append(
        {
            "name": "Use eye proxies before gaze",
            "status": "planned",
            "detail": "Model eye attention from foreground dwell, cursor zones, scroll velocity, and returns before collecting camera-based gaze.",
            "command": "future: enable local cursor-zone heatmaps with no raw pointer trail export",
        }
    )

    return {
        "current_depth": depth,
        "latest_app": latest.get("app", "none"),
        "latest_artifact": latest.get("artifact", "none"),
        "latest_detail_kind": _surface_detail_kind(latest) if latest else "",
        "application_attention": app_attention,
        "media_focus": media_focus,
        "eye_model": {
            "status": "proxy-first",
            "current_position": "camera/gaze is not collected; use frontmost dwell and future cursor/scroll zones first",
            "signals": [
                {"name": "foreground dwell", "status": "active", "detail": "what app/window held attention and for how long"},
                {"name": "switch path", "status": "active", "detail": "what you returned to after interruption"},
                {"name": "browser tab metadata", "status": "active" if browser_active else "ready", "detail": "site/title context without URL path/query by default"},
                {"name": "in-app UI labels", "status": "active" if ax_active else "gated", "detail": "only allowlisted apps at Depth 3"},
                {"name": "local OCR summaries", "status": "active" if ocr_active and ocr_status.get("status") == "ready" else "gated", "detail": "Apple Vision helper or Tesseract fallback; no stored pixels"},
                {"name": "cursor and scroll zones", "status": "planned", "detail": "aggregate heatmap, no text capture"},
                {"name": "webcam gaze", "status": "off", "detail": "only explicit local opt-in; no raw frames"},
            ],
        },
        "depth_ladder": ladder,
        "recommendations": recommendations,
    }


def _privacy_payload(
    config: dict[str, Any],
    events: list[dict[str, Any]],
    db_path: Path,
    *,
    expired_event_count: int = 0,
    oldest_event: str | None = None,
) -> dict[str, Any]:
    depth = int(config.get("context_capture_depth", 1))
    browser_depth = int(config.get("browser_tab_detail_min_depth", 2))
    ax_depth = int(config.get("accessibility_surface_min_depth", 3))
    ocr_depth = int(config.get("ocr_surface_min_depth", 4))
    captured = [
        "active app",
        "window title or redacted title",
        "timestamp",
        "dwell time",
        "derived work domain",
        "derived context graph nodes and privacy-gated edges",
        "derived working spheres and resume packs",
    ]
    not_captured = [
        "keystrokes",
        "screenshots",
        "clipboard",
        "microphone",
        "camera",
        "passwords",
        "tokens",
        "raw browser URL paths, queries, or fragments by default",
        "in-app player content unless a per-app Accessibility/OCR connector is explicitly enabled",
    ]
    if config.get("enable_browser_tab_details", True) and depth >= browser_depth:
        apps = ", ".join(config.get("browser_tab_detail_apps", []))
        captured.append(f"browser tab title and sanitized URL domain for: {apps}")
    if config.get("enable_accessibility_surface_details", True) and depth >= ax_depth:
        apps = ", ".join(config.get("accessibility_surface_detail_apps", []))
        captured.append(f"allowlisted Accessibility UI labels for: {apps}")
    if config.get("enable_ocr_surface_details", True) and depth >= ocr_depth:
        apps = ", ".join(config.get("ocr_surface_detail_apps", []))
        captured.append(f"redacted local OCR summaries for: {apps}")

    return {
        "capture_window_title": bool(config.get("capture_window_title", True)),
        "redact_sensitive_titles": bool(config.get("redact_sensitive_titles", True)),
        "mask_pii": bool(config.get("mask_pii", True)),
        "mask_configured_names": bool(config.get("mask_configured_names", True)),
        "mask_ip_addresses": bool(config.get("mask_ip_addresses", True)),
        "redact_url_paths": bool(config.get("redact_url_paths", True)),
        "collection_paused": bool(config.get("collection_paused", False)),
        "retention_days": int(config.get("retention_days", 30)),
        "expired_event_count": int(expired_event_count),
        "oldest_event": oldest_event,
        "browser_tab_details": bool(config.get("enable_browser_tab_details", True) and depth >= browser_depth),
        "accessibility_surface_details": bool(
            config.get("enable_accessibility_surface_details", True) and depth >= ax_depth
        ),
        "ocr_surface_details": bool(config.get("enable_ocr_surface_details", True) and depth >= ocr_depth),
        "ocr_provider": ocr_provider_status(config),
        "data_location": str(db_path.expanduser()),
        "redaction_summary": _redaction_summary(events),
        "captured": captured,
        "not_captured": not_captured,
        "connectors": registry_summary(config),
        "connector_activity": _connector_activity(events),
    }



def _connector_activity(events: list[dict[str, Any]]) -> dict[str, Any]:
    """What the connectors actually did, from observed events.

    The registry says what a connector *may* store. This says what it *did*,
    where each value came from, and how often a costlier source was avoided --
    which is the number worth watching, because it is the whole justification
    for this layer.
    """
    by_connector: dict[str, dict[str, Any]] = {}
    provenance_counts: dict[str, int] = {}
    avoided: dict[str, int] = {}
    total_captured = 0

    for event in events:
        structured = (event.get("metadata") or {}).get("structured") or {}
        if not isinstance(structured, dict) or structured.get("status") != "captured":
            continue
        total_captured += 1
        ident = str(structured.get("connector", "unknown"))
        row = by_connector.setdefault(
            ident,
            {
                "connector": ident,
                "display_name": structured.get("display_name", ident),
                "events": 0,
                "fields_seen": {},
                "confidence_sum": 0.0,
                "redaction_findings": {},
            },
        )
        row["events"] += 1
        row["confidence_sum"] += float(structured.get("confidence", 0.0) or 0.0)
        for name in (structured.get("fields") or {}):
            row["fields_seen"][name] = int(row["fields_seen"].get(name, 0)) + 1
        for key, count in (structured.get("redaction_findings") or {}).items():
            row["redaction_findings"][key] = int(row["redaction_findings"].get(key, 0)) + int(count)
        for source in (structured.get("provenance") or {}).values():
            provenance_counts[str(source)] = provenance_counts.get(str(source), 0) + 1
        for source in structured.get("sources_not_needed") or []:
            avoided[str(source)] = avoided.get(str(source), 0) + 1

    rows = []
    for row in by_connector.values():
        events_seen = max(row.pop("events"), 1)
        confidence_sum = row.pop("confidence_sum")
        row["event_count"] = events_seen
        row["mean_confidence"] = round(confidence_sum / events_seen, 3)
        rows.append(row)
    rows.sort(key=lambda item: item["event_count"], reverse=True)

    return {
        "captured_events": total_captured,
        "connectors": rows,
        "provenance_counts": provenance_counts,
        "costlier_sources_avoided": avoided,
        "explainer": (
            "Provenance shows which surface each value came from. "
            "Avoided counts show how often a cheaper source answered so a costlier "
            "one -- usually OCR -- was never opened."
        ),
    }


def _collector_status() -> dict[str, Any]:
    return service_status(SENSOR_SERVICE)


def build_overview(
    *,
    db_path: Path,
    config_path: Path,
    days: int,
    limit: int,
) -> dict[str, Any]:
    config = load_config(config_path)
    subject_id = config["subject_id"]
    store = open_event_store(db_path, config)
    events = store.fetch_window(subject_id=subject_id, days=days)
    total_count = store.count_events(subject_id=subject_id)
    retention_days = int(config.get("retention_days", 30))
    retention_cutoff = utc_now() - timedelta(days=retention_days)
    expired_event_count = store.count_before(subject_id=subject_id, cutoff=retention_cutoff)
    oldest_event = store.oldest_event(subject_id=subject_id)
    store.close()

    total_dwell = sum(float(event["dwell_seconds"]) for event in events)
    profile = build_digital_twin_signature(events, short_days=min(5, days), long_days=days)
    context_graph = (
        build_context_graph(events, config, days=days)
        if config.get("enable_context_graph", True)
        else {
            "status": "disabled",
            "days": days,
            "nodes": [],
            "edges": [],
            "stats": {"node_count": 0, "edge_count": 0, "events": len(events)},
            "pipeline": [],
            "privacy_gates": [],
            "top_relationships": [],
        }
    )
    working_spheres = (
        build_working_spheres(events, config, days=days)
        if config.get("enable_working_spheres", True)
        else {
            "status": "disabled",
            "days": days,
            "spheres": [],
            "timeline": [],
            "transitions": [],
            "stats": {"sphere_count": 0, "events": len(events)},
            "pipeline": [],
            "explanations": [],
        }
    )
    context_pack = build_context_pack(
        events,
        config,
        days=days,
        purpose="coding",
        target="kiro",
        max_events=8,
        activities=working_spheres,
        db_path=db_path,
    )
    learning = build_learning_state(
        events,
        config,
        subject_id=subject_id,
        db_path=db_path,
        days=days,
    )
    surface_details = _surface_details(events, config)
    recent_events = sorted(events, key=lambda item: item["ts_start"], reverse=True)[:limit]

    first_event = events[0]["ts_start"] if events else None
    last_event = events[-1]["ts_start"] if events else None
    last_age_seconds = None
    if last_event:
        last_age_seconds = max(0, round((utc_now() - parse_dt(last_event)).total_seconds()))

    collector = _collector_status()
    collector["collection_paused"] = bool(config.get("collection_paused", False))
    dashboard = service_status(DASHBOARD_SERVICE)
    fleet = build_fleet_status(
        events,
        config,
        db_path=db_path,
        days=days,
        total_count=total_count,
        collector_status=collector,
        dashboard_status=dashboard,
    )

    return {
        "subject_id": subject_id,
        "days": days,
        "generated_at": utc_now().isoformat(),
        "totals": {
            "events_in_window": len(events),
            "events_all_time": total_count,
            "dwell_seconds": round(total_dwell, 2),
            "hours": _seconds_to_hours(total_dwell),
            "first_event": first_event,
            "last_event": last_event,
            "last_age_seconds": last_age_seconds,
        },
        "collector": collector,
        "dashboard": dashboard,
        "fleet": fleet,
        "profile": profile,
        "context_graph": context_graph,
        "working_spheres": working_spheres,
        "context_pack": context_pack,
        "learning": learning,
        "insights": _interpret(profile, events),
        "domains": _domain_summary(events),
        "top_apps": _top_items(events, "app"),
        "top_artifacts": _top_items(events, "artifact"),
        "surface_details": surface_details,
        "attention_depth": _attention_depth_payload(events, config, surface_details),
        "daily_activity": _daily_activity(events),
        "hourly_heatmap": _hourly_heatmap(events),
        "transitions": _transitions(events),
        "recent_events": [_serialize_event(event) for event in recent_events],
        "privacy": _privacy_payload(
            config,
            events,
            db_path,
            expired_event_count=expired_event_count,
            oldest_event=oldest_event,
        ),
    }


def _set_collection_paused(config_path: Path, paused: bool) -> dict[str, Any]:
    ensure_config(config_path)
    config = load_config(config_path)
    config["collection_paused"] = paused
    write_config(config, config_path)
    return {
        "collection_paused": paused,
        "status": "paused" if paused else "collecting",
    }


def _purge_retention(db_path: Path, config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    subject_id = config["subject_id"]
    retention_days = int(config.get("retention_days", 30))
    cutoff = utc_now() - timedelta(days=retention_days)
    store = open_event_store(db_path, config)
    try:
        deleted = store.delete_before(subject_id=subject_id, cutoff=cutoff)
        remaining = store.count_events(subject_id=subject_id)
    finally:
        store.close()
    return {
        "deleted": deleted,
        "remaining": remaining,
        "retention_days": retention_days,
        "cutoff": cutoff.isoformat(),
    }


class TwinDashboardHandler(BaseHTTPRequestHandler):
    server_version = "DigitalTwinDashboard/0.1"

    def _trusted_request(self, *, api: bool = False) -> bool:
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin not in {f"http://{item}" for item in allowed}):
            self._send_json({"error": "Untrusted dashboard origin or host"}, HTTPStatus.FORBIDDEN)
            return False
        if api:
            token = self.headers.get("X-DTS-Token", "")
            if self.headers.get("Sec-Fetch-Site") == "cross-site" or not secrets.compare_digest(token, self.server.session_token):
                self._send_json({"error": "Dashboard session expired. Reload the page."}, HTTPStatus.FORBIDDEN)
                return False
        return True

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "verbose", False):
            super().log_message(format, *args)

    def _query(self) -> dict[str, list[str]]:
        parsed = urllib.parse.urlparse(self.path)
        return urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def _send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        if length > 16_384:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length).decode("utf-8")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _send_static(self, route: str) -> None:
        names = {"/": "index.html", "/assets/app.js": "app.js", "/assets/app.css": "app.css"}
        name = names.get(route)
        if name is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            files = resources.files("digital_twin_sensor.ui_static")
            content = (files / name).read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if name == "index.html":
            content = content.replace(b"__DTS_SESSION_TOKEN__", self.server.session_token.encode("ascii"))

        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if not self._trusted_request(api=route.startswith("/api/")):
            return
        query = self._query()

        try:
            if route == "/api/resume":
                config = load_config(self.server.config_path)
                self._send_json(build_resume_view(self.server.db_path, config,
                                                 sphere_id=query.get("sphere_id", [None])[0],
                                                 days=_safe_int(query.get("days", [None])[0], 14)))
                return
            if route == "/api/overview":
                days = _safe_int(query.get("days", [None])[0], 14)
                limit = _safe_int(query.get("limit", [None])[0], 80, 1, 500)
                self._send_json(
                    build_overview(
                        db_path=self.server.db_path,
                        config_path=self.server.config_path,
                        days=days,
                        limit=limit,
                    )
                )
                return

            if route == "/api/events":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                limit = _safe_int(query.get("limit", [None])[0], 250, 1, 1000)
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                events = sorted(events, key=lambda item: item["ts_start"], reverse=True)[:limit]
                self._send_json([_serialize_event(event) for event in events])
                return

            if route == "/api/profile":
                config = load_config(self.server.config_path)
                short_days = _safe_int(query.get("short_days", [None])[0], 5)
                long_days = _safe_int(query.get("long_days", [None])[0], 14)
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=long_days)
                store.close()
                self._send_json(build_digital_twin_signature(events, short_days=short_days, long_days=long_days))
                return

            if route == "/api/context-graph":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                max_nodes = _safe_int(
                    query.get("max_nodes", [None])[0],
                    int(config.get("context_graph_max_nodes", 70)),
                    10,
                    250,
                )
                max_edges = _safe_int(
                    query.get("max_edges", [None])[0],
                    int(config.get("context_graph_max_edges", 140)),
                    10,
                    500,
                )
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                self._send_json(
                    build_context_graph(
                        events,
                        config,
                        days=days,
                        max_nodes=max_nodes,
                        max_edges=max_edges,
                    )
                )
                return

            if route == "/api/activities":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                max_spheres = _safe_int(
                    query.get("max_spheres", [None])[0],
                    int(config.get("working_spheres_max_spheres", 12)),
                    1,
                    100,
                )
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                self._send_json(
                    build_working_spheres(
                        events,
                        config,
                        days=days,
                        max_spheres=max_spheres,
                    )
                )
                return

            if route == "/api/context-pack":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                max_events = _safe_int(query.get("max_events", [None])[0], 8, 1, 12)
                purpose = query.get("purpose", ["coding"])[0].strip()
                target = query.get("target", ["kiro"])[0].strip() or "kiro"
                sphere_id = query.get("sphere_id", [None])[0]
                if sphere_id is not None:
                    sphere_id = sphere_id.strip() or None
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                self._send_json(
                    build_context_pack(
                        events,
                        config,
                        days=days,
                        purpose=purpose,
                        target=target,
                        sphere_id=sphere_id,
                        max_events=max_events,
                        db_path=self.server.db_path,
                    )
                )
                return

            if route == "/api/learning":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                self._send_json(
                    build_learning_state(
                        events,
                        config,
                        subject_id=config["subject_id"],
                        db_path=self.server.db_path,
                        days=days,
                    )
                )
                return

            if route == "/api/fleet":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                total_count = store.count_events(subject_id=config["subject_id"])
                store.close()
                self._send_json(
                    build_fleet_status(
                        events,
                        config,
                        db_path=self.server.db_path,
                        days=days,
                        total_count=total_count,
                    )
                )
                return

            if route == "/api/health":
                stale_after = _safe_int(query.get("stale_after", [None])[0], 180, 30, 3600)
                self._send_json(
                    build_health_report(
                        db_path=self.server.db_path,
                        config_path=self.server.config_path,
                        stale_after_seconds=stale_after,
                    )
                )
                return

            if route == "/api/query":
                config = load_config(self.server.config_path)
                text = query.get("q", [""])[0].strip()
                days = _safe_int(query.get("days", [None])[0], 14)
                top_k = _safe_int(query.get("top_k", [None])[0], 8, 1, 50)
                store = open_event_store(self.server.db_path, config)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                profile = build_digital_twin_signature(events, short_days=min(5, days), long_days=days)
                self._send_json(retrieve(text, events, profile, top_k=top_k))
                return

            if route == "/" or route.startswith("/assets/"):
                self._send_static(route)
                return

            self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        if not self._trusted_request(api=True):
            return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in {
            "/api/collect-once",
            "/api/feedback",
            "/api/feedback/resolve",
            "/api/resume",
            "/api/admin/watchdog",
            "/api/admin/pause",
            "/api/admin/resume",
            "/api/admin/purge-retention",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            config = load_config(self.server.config_path)
            if parsed.path == "/api/resume":
                self._send_json(resume_action(self.server.db_path, config, self._read_json_body()))
                return
            if parsed.path == "/api/feedback/resolve":
                payload = self._read_json_body()
                store = LearningStore(self.server.db_path, config=config)
                try:
                    resolved = store.resolve_feedback(subject_id=config["subject_id"], feedback_id=int(payload.get("feedback_id", 0)))
                finally:
                    store.close()
                self._send_json({"resolved": resolved}, HTTPStatus.OK if resolved else HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/api/feedback":
                payload = self._read_json_body()
                store = LearningStore(self.server.db_path, config=config)
                try:
                    try:
                        feedback = store.add_feedback(
                            subject_id=config["subject_id"],
                            pack_id=str(payload.get("pack_id", "")).strip(),
                            sphere_id=str(payload.get("sphere_id") or "").strip() or None,
                            evidence_key=str(payload.get("evidence_key") or "").strip() or None,
                            scope=str(payload.get("scope") or "pack"),
                            label=str(payload.get("label") or ""),
                            purpose=str(payload.get("purpose") or "coding"),
                            target=str(payload.get("target") or "kiro"),
                            note=str(payload.get("note") or ""),
                            metadata={"source": "dashboard"},
                            config=config,
                        )
                    except ValueError as exc:
                        self._send_json({"stored": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                        return
                finally:
                    store.close()
                self._send_json({"stored": True, "feedback": feedback})
                return

            if parsed.path == "/api/admin/watchdog":
                self._send_json(
                    run_watchdog(
                        db_path=self.server.db_path,
                        config_path=self.server.config_path,
                        stale_after_seconds=180,
                        fix=True,
                    )
                )
                return

            if parsed.path == "/api/admin/pause":
                self._send_json(_set_collection_paused(self.server.config_path, True))
                return

            if parsed.path == "/api/admin/resume":
                self._send_json(_set_collection_paused(self.server.config_path, False))
                return

            if parsed.path == "/api/admin/purge-retention":
                query = urllib.parse.parse_qs(parsed.query)
                if query.get("confirm", [""])[0] != "purge-retention":
                    self._send_json(
                        {"error": "purge requires confirm=purge-retention"},
                        HTTPStatus.BAD_REQUEST,
                    )
                    return
                self._send_json(_purge_retention(self.server.db_path, self.server.config_path))
                return

            if config.get("collection_paused", False):
                self._send_json({"stored": False, "reason": "collection_paused"})
                return

            event = build_event(config, float(config.get("sample_interval_seconds", 15)))
            if event is None:
                self._send_json({"stored": False, "reason": "ignored_app"})
                return
            store = open_event_store(self.server.db_path, config)
            event_id = store.insert_event(event)
            store.close()
            event["id"] = event_id
            self._send_json({"stored": True, "event": _serialize_event(event)})
        except ResumeConflict as exc:
            self._send_json({"stored": False, "error": str(exc)}, HTTPStatus.CONFLICT)
        except ValueError as exc:
            self._send_json({"stored": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_json({"stored": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


class TwinDashboardServer(ThreadingHTTPServer):
    db_path: Path
    config_path: Path
    verbose: bool

    def __init__(self, server_address, handler):
        if server_address[0] not in {"127.0.0.1", "localhost"}:
            raise ValueError("Dashboard must bind to loopback; remote administration is not supported")
        self.session_token = secrets.token_urlsafe(32)
        super().__init__(server_address, handler)


def choose_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        result = sock.connect_ex(("127.0.0.1", preferred))
    if result != 0:
        return preferred

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_dashboard(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    verbose: bool = False,
) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Dashboard must bind to loopback")
    ensure_config(config_path)
    open_event_store(db_path, load_config(config_path)).close()
    actual_port = choose_port(port)
    server = TwinDashboardServer((host, actual_port), TwinDashboardHandler)
    server.db_path = Path(db_path).expanduser()
    server.config_path = Path(config_path).expanduser()
    server.verbose = verbose

    url = f"http://{host}:{actual_port}"
    print(f"Digital Twin Console running at {url}")
    print("Press Ctrl-C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()
