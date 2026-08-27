from __future__ import annotations

import json
import mimetypes
import os
import socket
import subprocess
import urllib.parse
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

from .collectors.macos_active_window import build_event
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, ensure_config, load_config
from .query import retrieve
from .store import EventStore, parse_dt, utc_now
from .twin import build_digital_twin_signature


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


def _transitions(events: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    previous = None
    for event in sorted(events, key=lambda item: item["ts_start"]):
        current = event["domain"]
        if previous and previous != current:
            counter[f"{previous} -> {current}"] += 1
        previous = current
    return [{"transition": name, "count": count} for name, count in counter.most_common(limit)]


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


def _collector_status() -> dict[str, Any]:
    label = "com.local.digital-twin-sensor"
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

    text = result.stdout
    state = "unknown"
    pid = None
    last_exit = None
    for line in text.splitlines():
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
    recent_events = sorted(events, key=lambda item: item["ts_start"], reverse=True)[:limit]

    first_event = events[0]["ts_start"] if events else None
    last_event = events[-1]["ts_start"] if events else None
    last_age_seconds = None
    if last_event:
        last_age_seconds = max(0, round((utc_now() - parse_dt(last_event)).total_seconds()))

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
        "collector": _collector_status(),
        "profile": profile,
        "insights": _interpret(profile, events),
        "domains": _domain_summary(events),
        "top_apps": _top_items(events, "app"),
        "top_artifacts": _top_items(events, "artifact"),
        "daily_activity": _daily_activity(events),
        "hourly_heatmap": _hourly_heatmap(events),
        "transitions": _transitions(events),
        "recent_events": [_serialize_event(event) for event in recent_events],
        "privacy": {
            "capture_window_title": bool(config.get("capture_window_title", True)),
            "redact_sensitive_titles": bool(config.get("redact_sensitive_titles", True)),
            "data_location": str(db_path.expanduser()),
            "captured": [
                "active app",
                "window title or redacted title",
                "timestamp",
                "dwell time",
                "derived work domain",
            ],
            "not_captured": [
                "keystrokes",
                "screenshots",
                "clipboard",
                "microphone",
                "camera",
                "passwords",
                "tokens",
            ],
        },
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
