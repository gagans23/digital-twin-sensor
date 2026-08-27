from __future__ import annotations

import json
import os
import pwd
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


DEFAULT_CONFIG: dict[str, Any] = {
    "subject_id": os.environ.get("USER", "local-user"),
    "sample_interval_seconds": 15,
    "capture_window_title": True,
    "redact_sensitive_titles": True,
    "record_ignored_apps_as_system_events": True,
    "mask_pii": True,
    "mask_configured_names": True,
    "mask_ip_addresses": True,
    "redact_url_paths": True,
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
