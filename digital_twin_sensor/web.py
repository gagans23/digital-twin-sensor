from __future__ import annotations

import json
import mimetypes
import socket
import urllib.parse
import webbrowser
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

from .collectors.macos_active_window import build_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ensure_config, load_config
from .context_graph import build_context_graph
from .fleet import DASHBOARD_SERVICE, SENSOR_SERVICE, build_fleet_status, service_status
from .query import retrieve
from .store import EventStore, parse_dt, utc_now
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
    depth = int(config.get("context_capture_depth", 1))
    browser_min_depth = int(config.get("browser_tab_detail_min_depth", 2))

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


def _privacy_payload(config: dict[str, Any], events: list[dict[str, Any]], db_path: Path) -> dict[str, Any]:
    depth = int(config.get("context_capture_depth", 1))
    browser_depth = int(config.get("browser_tab_detail_min_depth", 2))
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

    return {
        "capture_window_title": bool(config.get("capture_window_title", True)),
        "redact_sensitive_titles": bool(config.get("redact_sensitive_titles", True)),
        "mask_pii": bool(config.get("mask_pii", True)),
        "mask_configured_names": bool(config.get("mask_configured_names", True)),
        "mask_ip_addresses": bool(config.get("mask_ip_addresses", True)),
        "redact_url_paths": bool(config.get("redact_url_paths", True)),
        "browser_tab_details": bool(config.get("enable_browser_tab_details", True) and depth >= browser_depth),
        "data_location": str(db_path.expanduser()),
        "redaction_summary": _redaction_summary(events),
        "captured": captured,
        "not_captured": not_captured,
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
    store = EventStore(db_path)
    events = store.fetch_window(subject_id=subject_id, days=days)
    total_count = store.count_events(subject_id=subject_id)
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
    recent_events = sorted(events, key=lambda item: item["ts_start"], reverse=True)[:limit]

    first_event = events[0]["ts_start"] if events else None
    last_event = events[-1]["ts_start"] if events else None
    last_age_seconds = None
    if last_event:
        last_age_seconds = max(0, round((utc_now() - parse_dt(last_event)).total_seconds()))

    collector = _collector_status()
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
        "insights": _interpret(profile, events),
        "domains": _domain_summary(events),
        "top_apps": _top_items(events, "app"),
        "top_artifacts": _top_items(events, "artifact"),
        "surface_details": _surface_details(events, config),
        "daily_activity": _daily_activity(events),
        "hourly_heatmap": _hourly_heatmap(events),
        "transitions": _transitions(events),
        "recent_events": [_serialize_event(event) for event in recent_events],
        "privacy": _privacy_payload(config, events, db_path),
    }


class TwinDashboardHandler(BaseHTTPRequestHandler):
    server_version = "DigitalTwinDashboard/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        if getattr(self.server, "verbose", False):
            super().log_message(format, *args)

    def _query(self) -> dict[str, list[str]]:
        parsed = urllib.parse.urlparse(self.path)
        return urllib.parse.parse_qs(parsed.query)

    def _send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(value, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, route: str) -> None:
        name = "index.html" if route in {"", "/"} else route.removeprefix("/").removeprefix("assets/")
        try:
            files = resources.files("digital_twin_sensor.ui_static")
            content = (files / name).read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        query = self._query()

        try:
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
                store = EventStore(self.server.db_path)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                events = sorted(events, key=lambda item: item["ts_start"], reverse=True)[:limit]
                self._send_json([_serialize_event(event) for event in events])
                return

            if route == "/api/profile":
                config = load_config(self.server.config_path)
                short_days = _safe_int(query.get("short_days", [None])[0], 5)
                long_days = _safe_int(query.get("long_days", [None])[0], 14)
                store = EventStore(self.server.db_path)
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
                store = EventStore(self.server.db_path)
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
                store = EventStore(self.server.db_path)
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

            if route == "/api/fleet":
                config = load_config(self.server.config_path)
                days = _safe_int(query.get("days", [None])[0], 14)
                store = EventStore(self.server.db_path)
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

            if route == "/api/query":
                config = load_config(self.server.config_path)
                text = query.get("q", [""])[0].strip()
                days = _safe_int(query.get("days", [None])[0], 14)
                top_k = _safe_int(query.get("top_k", [None])[0], 8, 1, 50)
                store = EventStore(self.server.db_path)
                events = store.fetch_window(subject_id=config["subject_id"], days=days)
                store.close()
                profile = build_digital_twin_signature(events, short_days=min(5, days), long_days=days)
                self._send_json(retrieve(text, events, profile, top_k=top_k))
                return

            if route == "/" or route.startswith("/assets/"):
                self._send_static(route)
                return

            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/collect-once":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            config = load_config(self.server.config_path)
            event = build_event(config, float(config.get("sample_interval_seconds", 15)))
            if event is None:
                self._send_json({"stored": False, "reason": "ignored_app"})
                return
            store = EventStore(self.server.db_path)
            event_id = store.insert_event(event)
            store.close()
            event["id"] = event_id
            self._send_json({"stored": True, "event": _serialize_event(event)})
        except Exception as exc:
            self._send_json({"stored": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


class TwinDashboardServer(ThreadingHTTPServer):
    db_path: Path
    config_path: Path
    verbose: bool


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
    ensure_config(config_path)
    EventStore(db_path).close()
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
