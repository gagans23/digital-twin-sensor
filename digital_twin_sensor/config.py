from __future__ import annotations

import json
import os
import platform
import pwd
import socket
import hashlib
from pathlib import Path
from typing import Any


APP_DIR = Path.home() / ".digital-twin-sensor"
DEFAULT_DB_PATH = APP_DIR / "events.sqlite"
DEFAULT_CONFIG_PATH = APP_DIR / "config.json"


def _default_name_terms() -> list[str]:
    terms = set()
    username = os.environ.get("USER", "").strip()
    if len(username) >= 3:
        terms.add(username)

    try:
        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",", 1)[0].strip()
    except Exception:
        gecos = ""

    if gecos:
        terms.add(gecos)
        for part in gecos.replace(".", " ").replace("_", " ").split():
            if len(part) >= 3:
                terms.add(part)

    return sorted(terms, key=str.lower)


def _default_device_id() -> str:
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


def _default_device_name() -> str:
    hostname = socket.gethostname().split(".", 1)[0].strip()
    return hostname or f"{platform.system()} endpoint"


DEFAULT_CONFIG: dict[str, Any] = {
    "subject_id": os.environ.get("USER", "local-user"),
    "sample_interval_seconds": 15,
    "collection_paused": False,
    "encrypt_at_rest": False,
    "capture_window_title": True,
    "redact_sensitive_titles": True,
    "record_ignored_apps_as_system_events": True,
    "mask_pii": True,
    "mask_configured_names": True,
    "mask_ip_addresses": True,
    "redact_url_paths": True,
    "context_capture_depth": 1,
    "enable_context_graph": True,
    "context_graph_max_nodes": 70,
    "context_graph_max_edges": 140,
    "context_graph_include_system_events": False,
    "enable_working_spheres": True,
    "working_spheres_max_spheres": 12,
    "working_spheres_include_system_events": False,
    "working_spheres_session_gap_minutes": 45,
    "working_spheres_match_threshold": 0.42,
    "enable_browser_tab_details": True,
    "browser_tab_detail_min_depth": 2,
    "browser_tab_detail_apps": ["Safari", "Google Chrome"],
    "browser_tab_store_url_path": False,
    "browser_tab_store_query": False,
    "enable_accessibility_surface_details": True,
    "accessibility_surface_min_depth": 3,
    "accessibility_surface_detail_apps": ["Ibo Pro Player"],
    "accessibility_surface_max_items": 28,
    "accessibility_surface_max_hints": 10,
    "accessibility_surface_text_limit": 96,
    "enable_eye_proxy_model": True,
    "eye_proxy_collect_cursor": False,
    "eye_proxy_collect_camera_gaze": False,
    "retention_days": 30,
    "fleet_enabled": True,
    "fleet_device_id": _default_device_id(),
    "fleet_device_name": _default_device_name(),
    "fleet_policy_name": "Local Enterprise Baseline",
    "fleet_policy_version": "local-dev",
    "fleet_control_plane_url": "",
    "fleet_sync_enabled": False,
    "fleet_upload_mode": "summaries_only",
    "fleet_raw_event_upload": False,
    "fleet_allowed_export_targets": ["local_file", "kiro", "codex", "gitlab"],
    "name_terms_to_mask": _default_name_terms(),
    "ignored_apps": ["loginwindow", "ScreenSaverEngine"],
    "sensitive_title_keywords": [
        "password",
        "passcode",
        "otp",
        "2fa",
        "mfa",
        "bank",
        "card number",
        "secret",
        "private key",
        "recovery phrase",
    ],
    "domain_rules": [
        {
            "domain": "coding",
            "apps": ["Code", "Cursor", "Xcode", "Kiro", "Terminal", "iTerm2"],
            "keywords": ["github", "pull request", "issue", "repo", "localhost"],
        },
        {
            "domain": "communication",
            "apps": ["Slack", "Microsoft Teams", "Discord", "Mail", "Messages"],
            "keywords": ["gmail", "inbox", "email", "calendar invite"],
        },
        {
            "domain": "documents",
            "apps": ["Pages", "Microsoft Word", "Google Docs", "Preview"],
            "keywords": ["docs.google", ".docx", ".pdf", "proposal", "brief"],
        },
        {
            "domain": "browser-research",
            "apps": ["Safari", "Google Chrome", "Arc", "Firefox"],
            "keywords": ["arxiv", "docs", "stackoverflow", "search", "wikipedia"],
        },
        {
            "domain": "planning",
            "apps": ["Calendar", "Reminders", "Notion", "Todoist", "Things"],
            "keywords": ["roadmap", "kanban", "todo", "meeting", "spec"],
        },
        {
            "domain": "data",
            "apps": ["Microsoft Excel", "Numbers", "Tableau"],
            "keywords": ["spreadsheet", ".csv", "dashboard", "metrics"],
        },
    ],
}


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_CONFIG)

    with path.open("r", encoding="utf-8") as f:
        loaded = json.load(f)

    config = dict(DEFAULT_CONFIG)
    config.update(loaded)
    return config


def ensure_config(path: Path = DEFAULT_CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
            f.write("\n")
        return path

    with path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value
            changed = True

    if changed:
        with path.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
    return path


def write_config(config: dict[str, Any], path: Path = DEFAULT_CONFIG_PATH) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    return path
