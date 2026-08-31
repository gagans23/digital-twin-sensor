"""Apply connector manifests to captured surfaces.

The contract this module keeps, and which the tests hold it to:

1. A field not declared in the manifest never appears in the output.
2. A source the manifest did not declare is never read.
3. A source above the user's configured capture depth is never read.
4. Every stored value carries where it came from and how confident we are.
5. Cheaper sources win. If Accessibility answers, OCR is never invoked.

Point five is the reason this layer exists. OCR is the most invasive thing the
sensor can do, and most of the time an app has already told us what we needed
in a window title.
"""

from __future__ import annotations

import re
from typing import Any

from ..redaction import redact_text
from .manifest import (
    SOURCE_MIN_DEPTH,
    FieldSpec,
    Manifest,
    load_manifests,
)

# Confidence by provenance. These are ordering priors, not measurements: a value
# the app told us directly is more trustworthy than one recovered from pixels.
# They have never been calibrated against labelled data and should not be cited
# as a result. See docs/UNDER_THE_HOOD.md.
SOURCE_CONFIDENCE = {
    "window_title": 0.72,
    "browser_tab": 0.88,
    "accessibility": 0.80,
    "ocr": 0.45,
}

_CACHE: list[Manifest] | None = None


def registry(reload: bool = False) -> list[Manifest]:
    global _CACHE
    if _CACHE is None or reload:
        _CACHE = load_manifests()
    return _CACHE


def connector_for_app(app: str, manifests: list[Manifest] | None = None) -> Manifest | None:
    for manifest in manifests if manifests is not None else registry():
        if manifest.matches_app(app):
            return manifest
    return None


def available_sources(manifest: Manifest, config: dict[str, Any]) -> list[str]:
    """Sources this connector may read at the user's current depth, cheapest first."""
    depth = int(config.get("context_capture_depth", 1))
    return [s for s in manifest.sources if SOURCE_MIN_DEPTH[s] <= depth]


def _source_texts(payload: dict[str, Any]) -> list[str]:
    """Flatten a surface payload into candidate strings for pattern matching."""
    out: list[str] = []
    for key in ("title", "window_title", "summary"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            out.append(value)
    hints = payload.get("text_hints")
    if isinstance(hints, list):
        for hint in hints:
            if isinstance(hint, str):
                out.append(hint)
            elif isinstance(hint, dict) and isinstance(hint.get("text"), str):
                out.append(hint["text"])
    return out


def _coerce(spec: FieldSpec, raw: str, config: dict[str, Any]) -> tuple[Any, dict[str, int]]:
    """Apply the declared storage mode. This is the only path to a stored value."""
    value = raw.strip()[: spec.max_length]
    if spec.store == "count":
        digits = re.sub(r"[^0-9]", "", value)
        return (int(digits) if digits else None), {}
    if spec.store == "token":
        lowered = value.lower()
        for token in spec.tokens:
            if token in lowered:
                return token, {}
        return None, {}
    if spec.store == "domain":
        host = value.lower().split("/")[0].split(":")[0]
        return (host or None), {}
    result = redact_text(value, config)
    return (result.text or None), dict(result.findings)


def _extract_field(
    spec: FieldSpec, source: str, payload: dict[str, Any], config: dict[str, Any]
) -> tuple[Any, dict[str, int]] | None:
    if spec.from_key:
        # A token field is a search across everything the surface said, not a
        # coercion of whichever string happened to come first. "Playing" may be
        # the fourth hint; taking only the first would silently drop it.
        if spec.store == "token":
            for text in _source_texts(payload):
                value, found = _coerce(spec, text, config)
                if value is not None:
                    return value, found
            return None

        raw = payload.get(spec.from_key)
        if isinstance(raw, list):
            candidates = _source_texts({"text_hints": raw})
            raw = candidates[0] if candidates else None
        if isinstance(raw, str) and raw.strip():
            return _coerce(spec, raw, config)
        return None

    compiled = spec.compiled()
    if compiled is None:
        return None
    for text in _source_texts(payload):
        match = compiled.search(text)
        if match and match.group("value"):
            return _coerce(spec, match.group("value"), config)
    return None


def apply_connector(
    manifest: Manifest,
    surfaces: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Extract declared fields from whichever permitted sources answer.

    `surfaces` maps source name -> that source's sanitised payload. Sources the
    manifest did not declare, or that the current depth forbids, are ignored even
    if present.
    """
    permitted = available_sources(manifest, config)
    fields: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    confidence: dict[str, float] = {}
    findings: dict[str, int] = {}
    consulted: list[str] = []
    skipped_costlier: list[str] = []

    for spec in manifest.fields:
        for source in permitted:
            payload = surfaces.get(source)
            if not payload:
                continue
            if source not in consulted:
                consulted.append(source)
            extracted = _extract_field(spec, source, payload, config)
            if extracted is None:
                continue
            value, found = extracted
            if value is None or value == "":
                continue
            fields[spec.name] = value
            provenance[spec.name] = source
            confidence[spec.name] = SOURCE_CONFIDENCE.get(source, 0.5)
            for key, count in found.items():
                findings[key] = int(findings.get(key, 0)) + int(count)
            # Cheapest source that answers wins for this field; the loop breaks
            # before any costlier source is read.
            break

    # Belt and braces: the framework must not emit anything undeclared, even if a
    # future change to extraction gets this wrong.
    undeclared = set(fields) - set(manifest.field_names)
    if undeclared:  # pragma: no cover - guarded by tests, should be unreachable
        for key in undeclared:
            fields.pop(key, None)
            provenance.pop(key, None)
            confidence.pop(key, None)

    # A source is "not needed" only if it was available and never read at all.
    # Anything in `consulted` was genuinely opened, so it cannot also be listed here.
    skipped_costlier = [
        source for source in permitted
        if surfaces.get(source) and source not in consulted
    ]

    overall = round(sum(confidence.values()) / len(confidence), 3) if confidence else 0.0
    return {
        "connector": manifest.id,
        "connector_version": manifest.version,
        "display_name": manifest.display_name,
        "status": "captured" if fields else "empty",
        "fields": fields,
        "provenance": provenance,
        "field_confidence": confidence,
        "confidence": overall,
        "sources_permitted": permitted,
        "sources_consulted": consulted,
        "sources_not_needed": skipped_costlier,
        "declared_fields": sorted(manifest.field_names),
        "missing_fields": sorted(set(manifest.field_names) - set(fields)),
        "denied": list(manifest.denied),
        "redaction_findings": findings,
        "privacy": (
            "manifest-declared fields only; anything not declared cannot be stored"
        ),
    }


def structured_detail(
    app: str,
    surfaces: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Entry point used by the collector. Returns None when no connector matches."""
    if not config.get("enable_structured_connectors", True):
        return None
    manifest = connector_for_app(app)
    if manifest is None:
        return None
    depth = int(config.get("context_capture_depth", 1))
    if depth < manifest.min_depth:
        return {
            "connector": manifest.id,
            "connector_version": manifest.version,
            "display_name": manifest.display_name,
            "status": "below_depth",
            "fields": {},
            "required_depth": manifest.min_depth,
            "current_depth": depth,
            "privacy": "connector needs a higher capture depth than the user has enabled",
        }
    return apply_connector(manifest, surfaces, config)


def registry_summary(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """What the dashboard shows: every connector, what it may store, what it may not."""
    config = config or {}
    depth = int(config.get("context_capture_depth", 1))
    rows = []
    for manifest in registry():
        rows.append(
            {
                "id": manifest.id,
                "display_name": manifest.display_name,
                "version": manifest.version,
                "apps": list(manifest.apps),
                "min_depth": manifest.min_depth,
                "active": depth >= manifest.min_depth,
                "sources": list(manifest.sources),
                "sources_available_now": available_sources(manifest, config),
                "fields": [
                    {
                        "name": f.name,
                        "store": f.store,
                        "sensitivity": f.sensitivity,
                        "description": f.description,
                    }
                    for f in manifest.fields
                ],
                "denied": list(manifest.denied),
                "notes": manifest.notes,
            }
        )
    return rows
