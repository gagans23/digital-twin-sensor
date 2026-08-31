from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from ..redaction import redact_text


def _helper_path() -> Path:
    return Path.home() / ".digital-twin-sensor" / "macos-ocr-probe"


def ocr_detail_enabled(app: str, config: dict[str, Any]) -> bool:
    min_depth = int(config.get("ocr_surface_min_depth", 4))
    depth = int(config.get("context_capture_depth", 1))
    apps = {str(item).lower() for item in config.get("ocr_surface_detail_apps", [])}
    return (
        bool(config.get("enable_ocr_surface_details", True))
        and depth >= min_depth
        and app.lower() in apps
    )


def ocr_provider_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    providers = []
    helper = _helper_path()
    helper_ready = helper.exists()
    if platform.system() == "Darwin":
        providers.append(
            {
                "name": "apple_vision",
                "status": "ready" if helper_ready else "missing_helper",
                "detail": str(helper),
            }
        )
    tesseract = shutil.which(str(config.get("ocr_tesseract_binary", "tesseract")))
    tesseract_status = "ready" if tesseract else "not_installed"
    if platform.system() == "Darwin" and tesseract and not helper_ready:
        tesseract_status = "missing_helper"
    providers.append(
        {
            "name": "tesseract",
            "status": tesseract_status,
            "detail": tesseract or "install tesseract for cross-platform offline OCR fallback",
        }
    )
    ready = {item["name"] for item in providers if item["status"] == "ready"}
    preferred = next((name for name in _provider_order(config) if name in ready), None)
    return {
        "status": "ready" if ready else "not_ready",
        "preferred": preferred,
        "providers": providers,
        "privacy": "OCR is local-only; screenshots are transient and text is redacted before storage.",
    }


def _provider_order(config: dict[str, Any]) -> list[str]:
    preferred = str(config.get("ocr_surface_provider", "apple_vision")).strip().lower()
    order = [preferred] if preferred in {"apple_vision", "tesseract"} else ["apple_vision"]
    for provider in ("apple_vision", "tesseract"):
        if provider not in order:
            order.append(provider)
    return order


def _run_macos_ocr_probe(app: str, config: dict[str, Any], provider: str) -> dict[str, Any] | None:
    if platform.system() != "Darwin":
        return None
    helper = _helper_path()
    if not helper.exists():
        return None

    max_lines = max(1, min(int(config.get("ocr_surface_max_lines", 12)), 40))
    min_confidence = max(0.0, min(float(config.get("ocr_surface_min_confidence", 0.35)), 1.0))
    tesseract = shutil.which(str(config.get("ocr_tesseract_binary", "tesseract"))) or ""
    if provider == "tesseract" and not tesseract:
        return None
    result = subprocess.run(
        [str(helper), app, str(max_lines), str(min_confidence), provider, tesseract],
        check=False,
        capture_output=True,
        text=True,
        timeout=max(3, min(int(config.get("ocr_surface_timeout_seconds", 8)), 20)),
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def sanitize_ocr_surface_detail(detail: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    text_limit = int(config.get("ocr_surface_text_limit", 120))
    max_hints = int(config.get("ocr_surface_max_hints", 8))
    findings: Counter[str] = Counter()
    hints: list[str] = []
    seen: set[str] = set()
    confidences = []

    for row in detail.get("lines", [])[: max(1, int(config.get("ocr_surface_max_lines", 12)))]:
        raw_text = _clean_text(row.get("text"), text_limit)
        if not raw_text:
            continue
        confidence = row.get("confidence")
        try:
            confidences.append(float(confidence))
        except (TypeError, ValueError):
            pass
        redacted = redact_text(raw_text, config)
        for key, value in redacted.findings.items():
            findings[str(key)] += int(value)
        safe = redacted.text.strip()
        if not safe or safe.lower() in seen:
            continue
        seen.add(safe.lower())
        hints.append(safe)
        if len(hints) >= max_hints:
            break

    avg_confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    summary = "; ".join(hints[:3])
    if len(summary) > 260:
        summary = summary[:257].rstrip() + "..."

    return {
        "kind": "ocr_summary",
        "status": "captured" if hints else "empty",
        "source": detail.get("source", "local_ocr"),
        "provider": detail.get("provider", "local"),
        "app": detail.get("app", ""),
        "window_title": redact_text(_clean_text(detail.get("window_title"), text_limit), config).text,
        "line_count": int(detail.get("line_count", len(detail.get("lines", [])))),
        "text_hints": hints,
        "summary": summary,
        "confidence": avg_confidence,
        "redaction_findings": dict(findings),
        "privacy": "temporary window image processed locally; pixels are not stored; only redacted OCR text hints and summary are persisted",
    }


def active_ocr_surface_detail(app: str, config: dict[str, Any]) -> dict[str, Any] | None:
    if not ocr_detail_enabled(app, config):
        return None

    raw = None
    for provider in _provider_order(config):
        raw = _run_macos_ocr_probe(app, config, provider)
        if raw and raw.get("status") == "captured":
            break
    if not raw or raw.get("status") != "captured":
        return None

    safe = sanitize_ocr_surface_detail(raw, config)
    return safe if safe.get("status") == "captured" else None
