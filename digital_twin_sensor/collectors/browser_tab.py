from __future__ import annotations

import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..redaction import redact_text
from ..observability import observed


SAFARI_TAB_SCRIPT = """
tell application "Safari"
  if (count of windows) is 0 then return ""
  set tabTitle to ""
  set tabUrl to ""
  try
    set tabTitle to name of current tab of front window
    set tabUrl to URL of current tab of front window
  end try
  return tabTitle & "\t" & tabUrl
end tell
"""

CHROME_TAB_SCRIPT = """
tell application "Google Chrome"
  if (count of windows) is 0 then return ""
  set tabTitle to ""
  set tabUrl to ""
  try
    set activeTab to active tab of front window
    set tabTitle to title of activeTab
    set tabUrl to URL of activeTab
  end try
  return tabTitle & "\t" & tabUrl
end tell
"""

SCRIPT_BY_APP = {
    "Google Chrome": CHROME_TAB_SCRIPT,
    "Safari": SAFARI_TAB_SCRIPT,
}


def browser_detail_enabled(app: str, config: dict[str, Any]) -> bool:
    min_depth = int(config.get("browser_tab_detail_min_depth", 2))
    depth = int(config.get("context_capture_depth", 1))
    apps = {str(item).lower() for item in config.get("browser_tab_detail_apps", [])}
    return (
        bool(config.get("enable_browser_tab_details", True))
        and depth >= min_depth
        and app.lower() in apps
        and app in SCRIPT_BY_APP
    )


def _run_script(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


@observed("collection.browser")
def active_browser_tab_detail(app: str, config: dict[str, Any]) -> dict[str, Any] | None:
    if not browser_detail_enabled(app, config):
        return None

    output = _run_script(SCRIPT_BY_APP[app])
    if not output:
        return None

    if "\t" in output:
        title, url = output.split("\t", 1)
    else:
        title, url = output, ""

    raw = {
        "kind": "browser_tab",
        "source": f"{app.lower().replace(' ', '_')}_applescript",
        "app": app,
        "title": title.strip(),
        "url": url.strip(),
    }
    safe = sanitize_browser_tab_detail(raw, config)
    return safe if safe.get("title") or safe.get("url_domain") else None


def sanitize_browser_url(url: str, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    url = str(url or "").strip()
    if not url:
        return {"url": "", "url_domain": "", "url_scheme": "", "url_path_policy": "none"}, {}

    try:
        parsed = urlsplit(url)
    except ValueError:
        return {"url": "[url]", "url_domain": "", "url_scheme": "", "url_path_policy": "invalid"}, {"url": 1}

    host = parsed.hostname or ""
    scheme = parsed.scheme or ""
    netloc = parsed.netloc
    if parsed.username or parsed.password:
        host = host or "redacted-host"
        netloc = host

    store_path = bool(config.get("browser_tab_store_url_path", False))
    store_query = bool(config.get("browser_tab_store_query", False))
    path = parsed.path if store_path else ("/[redacted-path]" if parsed.path else "")
    query = parsed.query if store_query else ""
    fragment = ""

    safe_url = urlunsplit((scheme, netloc, path, query, fragment))
    findings: dict[str, int] = {}
    if not store_path and parsed.path:
        findings["url"] = findings.get("url", 0) + 1
    if not store_query and parsed.query:
        findings["url"] = findings.get("url", 0) + 1
    if parsed.fragment:
        findings["url"] = findings.get("url", 0) + 1
    if parsed.username or parsed.password:
        findings["url"] = findings.get("url", 0) + 1

    redacted = redact_text(safe_url, config)
    for key, value in redacted.findings.items():
        findings[key] = findings.get(key, 0) + int(value)

    return {
        "url": redacted.text,
        "url_domain": host,
        "url_scheme": scheme,
        "url_path_policy": "stored" if store_path else "redacted",
        "url_query_policy": "stored" if store_query else "redacted",
    }, findings


def sanitize_browser_tab_detail(detail: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    title_result = redact_text(str(detail.get("title", "")).strip()[:240], config)
    url_detail, url_findings = sanitize_browser_url(str(detail.get("url", "")), config)
    findings = dict(title_result.findings)
    for key, value in url_findings.items():
        findings[key] = int(findings.get(key, 0)) + int(value)

    return {
        "kind": "browser_tab",
        "status": "captured",
        "source": detail.get("source", "browser_applescript"),
        "app": detail.get("app", "browser"),
        "title": title_result.text,
        **url_detail,
        "redaction_findings": findings,
        "privacy": "tab title redacted; URL path/query/fragment redacted by default",
    }
