from __future__ import annotations

import re
import subprocess
from collections import Counter
from typing import Any

from ..redaction import redact_text
from ..observability import observed


AX_SURFACE_SCRIPT = """
on run argv
  set expectedApp to item 1 of argv
  set maxItems to item 2 of argv as integer
  tell application "System Events"
    set frontApp to name of first application process whose frontmost is true
    if frontApp is not expectedApp then return ""
    set rows to ""
    try
      tell process frontApp
        set targetWindow to front window
        set observed to 0
        repeat with uiItem in entire contents of targetWindow
          if observed is greater than or equal to maxItems then exit repeat
          set roleText to ""
          set nameText to ""
          set valueText to ""
          try
            set roleText to role of uiItem as text
          end try
          try
            set nameText to name of uiItem as text
          end try
          try
            set valueText to value of uiItem as text
          end try
          if nameText is not "" or valueText is not "" then
            set rows to rows & roleText & tab & nameText & tab & valueText & linefeed
            set observed to observed + 1
          end if
        end repeat
      end tell
    end try
    return rows
  end tell
end run
"""


def accessibility_detail_enabled(app: str, config: dict[str, Any]) -> bool:
    min_depth = int(config.get("accessibility_surface_min_depth", 3))
    depth = int(config.get("context_capture_depth", 1))
    apps = {str(item).lower() for item in config.get("accessibility_surface_detail_apps", [])}
    return (
        bool(config.get("enable_accessibility_surface_details", True))
        and depth >= min_depth
        and app.lower() in apps
    )


def _run_script(app: str, max_items: int) -> str:
    result = subprocess.run(
        ["osascript", "-e", AX_SURFACE_SCRIPT, app, str(max_items)],
        check=False,
        capture_output=True,
        text=True,
        timeout=6,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _parse_rows(output: str) -> list[dict[str, str]]:
    rows = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        while len(parts) < 3:
            parts.append("")
        role, name, value = parts[:3]
        rows.append({"role": role.strip(), "name": name.strip(), "value": value.strip()})
    return rows


def sanitize_accessibility_surface_detail(
    detail: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    limit = int(config.get("accessibility_surface_text_limit", 96))
    max_hints = int(config.get("accessibility_surface_max_hints", 10))
    roles: Counter[str] = Counter()
    hints: list[str] = []
    findings: Counter[str] = Counter()
    seen: set[str] = set()

    for row in detail.get("elements", []):
        role = _clean_text(row.get("role"), 64) or "unknown"
        roles[role] += 1
        text = _clean_text(" ".join([str(row.get("name", "")), str(row.get("value", ""))]), limit)
        if not text:
            continue
        redacted = redact_text(text, config)
        for key, value in redacted.findings.items():
            findings[str(key)] += int(value)
        safe_text = redacted.text.strip()
        if not safe_text or safe_text.lower() in seen:
            continue
        seen.add(safe_text.lower())
        hints.append(safe_text)
        if len(hints) >= max_hints:
            break

    return {
        "kind": "accessibility_snapshot",
        "status": "captured" if roles or hints else "empty",
        "source": "macos_accessibility_tree",
        "app": detail.get("app", ""),
        "element_count": int(detail.get("element_count", len(detail.get("elements", [])))),
        "roles": [{"role": role, "count": int(count)} for role, count in roles.most_common(8)],
        "text_hints": hints,
        "redaction_findings": dict(findings),
        "privacy": "allowlisted Accessibility metadata; redacted labels only; no screenshots, keystrokes, clipboard, or raw video",
    }


@observed("collection.accessibility")
def active_accessibility_surface_detail(app: str, config: dict[str, Any]) -> dict[str, Any] | None:
    if not accessibility_detail_enabled(app, config):
        return None

    max_items = int(config.get("accessibility_surface_max_items", 28))
    output = _run_script(app, max(1, min(max_items, 80)))
    if not output:
        return None

    rows = _parse_rows(output)
    safe = sanitize_accessibility_surface_detail(
        {"app": app, "element_count": len(rows), "elements": rows},
        config,
    )
    return safe if safe.get("status") == "captured" else None
