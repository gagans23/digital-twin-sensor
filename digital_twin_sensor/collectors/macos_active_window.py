from __future__ import annotations

import re
import subprocess
from pathlib import Path
from datetime import timedelta
from typing import Any

from .accessibility_surface import active_accessibility_surface_detail
from .browser_tab import active_browser_tab_detail
from ..redaction import redact_text
from ..store import utc_now


ACTIVE_WINDOW_SCRIPT = """
tell application "System Events"
  set frontApp to name of first application process whose frontmost is true
  set winTitle to ""
  try
    tell process frontApp
      set winTitle to name of front window
    end tell
  end try
  return frontApp & "\t" & winTitle
end tell
"""


def _native_probe_path() -> Path:
    return Path.home() / ".digital-twin-sensor" / "macos-window-probe"


def _active_window_native() -> tuple[str, str] | None:
    probe = _native_probe_path()
    if not probe.exists():
        return None

    result = subprocess.run(
        [str(probe)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    if not output:
        return None

    if "\t" in output:
        app, title = output.split("\t", 1)
    else:
        app, title = output, ""
    return app.strip(), title.strip()


def active_window() -> tuple[str, str]:
    native_result = _active_window_native()
    if native_result is not None:
        return native_result

    result = subprocess.run(
        ["osascript", "-e", ACTIVE_WINDOW_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "Could not read active window. On macOS, grant Accessibility permission "
            f"to your terminal app. Details: {detail}"
        )

    output = result.stdout.strip()
    if "\t" in output:
        app, title = output.split("\t", 1)
    else:
        app, title = output, ""
    return app.strip(), title.strip()


def classify_domain(app: str, title: str, config: dict[str, Any]) -> str:
    haystack = f"{app} {title}".lower()
    for rule in config.get("domain_rules", []):
        apps = [item.lower() for item in rule.get("apps", [])]
        keywords = [item.lower() for item in rule.get("keywords", [])]
        if app.lower() in apps:
            return rule["domain"]
        if any(keyword in haystack for keyword in keywords):
            return rule["domain"]
    return "other"


def should_ignore(app: str, config: dict[str, Any]) -> bool:
    ignored = {item.lower() for item in config.get("ignored_apps", [])}
    return app.lower() in ignored


def scrub_title(title: str, config: dict[str, Any]) -> str:
    if not config.get("capture_window_title", True):
        return "[title capture disabled]"

    if not config.get("redact_sensitive_titles", True):
        return title

    lowered = title.lower()
    for keyword in config.get("sensitive_title_keywords", []):
        if keyword.lower() in lowered:
            return "[redacted sensitive title]"

    # Reduce very long, token-heavy titles. The sensor needs an artifact hint, not full text.
    return re.sub(r"\s+", " ", title).strip()[:240]


def build_event(config: dict[str, Any], dwell_seconds: float) -> dict[str, Any] | None:
    if config.get("collection_paused", False):
        return None

    app, raw_title = active_window()
    ignored = should_ignore(app, config)
    if ignored and not config.get("record_ignored_apps_as_system_events", True):
        return None

    surface_detail = None
    if not ignored:
        surface_detail = active_browser_tab_detail(app, config)
        if surface_detail is None:
            surface_detail = active_accessibility_surface_detail(app, config)
    if surface_detail and surface_detail.get("title"):
        raw_title = str(surface_detail["title"])

    raw_safe_title = f"[system state: {app}]" if ignored else scrub_title(raw_title, config)
    now = utc_now()
    start = now - timedelta(seconds=max(dwell_seconds, 0.1))
    domain_hint = ""
    if surface_detail:
        text_hints = " ".join(str(item) for item in surface_detail.get("text_hints", [])[:4])
        domain_hint = f"{surface_detail.get('url_domain', '')} {surface_detail.get('title', '')} {text_hints}"
    domain = "system" if ignored else classify_domain(app, f"{raw_safe_title} {domain_hint}", config)
    redacted_title = redact_text(raw_safe_title, config)
    title = redacted_title.text
    artifact = title if title else app
    redaction_findings = dict(redacted_title.findings)
    if surface_detail:
        for key, value in surface_detail.get("redaction_findings", {}).items():
            redaction_findings[key] = int(redaction_findings.get(key, 0)) + int(value)

    return {
        "subject_id": config["subject_id"],
        "source": "macos_active_window",
        "app": app,
        "title": title,
        "artifact": artifact,
        "domain": domain,
        "action": "system" if ignored else "focus",
        "ts_start": start.isoformat(),
        "ts_end": now.isoformat(),
        "dwell_seconds": dwell_seconds,
        "metadata": {
            "collector_version": "macos-active-window-v1",
            "ignored_app_recorded_as_system": ignored,
            "surface_detail": surface_detail,
            "redaction_findings": redaction_findings,
            "privacy": "no_keystrokes_no_screenshots_no_clipboard",
        },
    }
