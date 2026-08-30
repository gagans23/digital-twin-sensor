"""Collective synthesis over context captured by many sensors.

A single sensor answers "what was this person doing?". That is the easy half.
The layer that matters for an institution answers "what is *the work* here?" —
and it has to answer without ever letting one person's trace be reconstructed
from the output.

So the floor comes first: a theme is only emitted when enough distinct subjects
independently support it. Anything below the floor is withheld and *counted*, so
an operator can see that suppression happened rather than quietly receiving a
thinner answer. Below-floor suppression is the whole reason this layer can run
above the level of a team at all.

Nothing here reads raw events. It consumes the same gated working-sphere output
the local dashboard shows the person themselves, keyed by an opaque subject key.

    digital-twin-sensor synthesize --input bundles.json --min-subjects 5
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any

from .store import utc_now

DEFAULT_MIN_SUBJECTS = 5
DEFAULT_MAX_THEMES = 24
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "over", "your",
    "our", "their", "about", "after", "before", "then", "than", "when", "what",
    "untitled", "unknown", "system", "window", "document", "new", "open", "file",
}
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9-]{2,}")


def subject_key(value: str) -> str:
    """Opaque, stable, non-reversible. Synthesis never needs the real identity."""
    return "subj_" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _theme_tokens(label: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(label or "")
        if token.lower() not in STOPWORDS
    ]


def _theme_key(sphere: dict[str, Any]) -> str:
    """Group spheres by domain plus the strongest label tokens.

    Deliberately coarse. A finer key produces more themes, each supported by
    fewer subjects, and more of them fall below the floor — precision here buys
    nothing and costs suppression.
    """
    domain = str(sphere.get("domain") or "unknown").lower()
    tokens = sorted(set(_theme_tokens(str(sphere.get("label") or sphere.get("task") or ""))))[:3]
    return f"{domain}:{'-'.join(tokens) if tokens else 'general'}"


def _readable(theme_key: str) -> str:
    domain, _, rest = theme_key.partition(":")
    words = rest.replace("-", " ").strip()
    return f"{domain} — {words}" if words and words != "general" else domain


def _confidence(subjects: int, events: int, min_subjects: int) -> float:
    """Rises with corroboration across people, not with volume from one person."""
    breadth = min(1.0, subjects / max(min_subjects * 2, 1))
    depth = min(1.0, events / 40.0)
    return round(0.65 * breadth + 0.35 * depth, 3)


def synthesize_collective(
    bundles: list[dict[str, Any]],
    *,
    min_subjects: int = DEFAULT_MIN_SUBJECTS,
    max_themes: int = DEFAULT_MAX_THEMES,
    days: int = 14,
) -> dict[str, Any]:
    """Fold per-subject working spheres into themes that clear an aggregation floor.

    `bundles` is a list of {"subject_key": str, "activities": <build_working_spheres output>}.
    """
    if min_subjects < 2:
        raise ValueError("min_subjects must be at least 2; a floor of 1 is not a floor")

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"subjects": set(), "events": 0, "dwell_seconds": 0.0, "ages": [], "labels": set()}
    )
    seen_subjects: set[str] = set()

    for bundle in bundles:
        key = str(bundle.get("subject_key") or "")
        if not key:
            continue
        seen_subjects.add(key)
        activities = bundle.get("activities") or {}
        for sphere in activities.get("spheres", []) or []:
            theme = _theme_key(sphere)
            bucket = grouped[theme]
            bucket["subjects"].add(key)
            bucket["events"] += int(sphere.get("events", 0) or 0)
            bucket["dwell_seconds"] += float(sphere.get("dwell_seconds", 0.0) or 0.0)
            bucket["labels"].add(str(sphere.get("label") or ""))
            age = sphere.get("last_age_seconds")
            if isinstance(age, (int, float)):
                bucket["ages"].append(int(age))

    themes: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []

    for theme_key_value, bucket in grouped.items():
        support = len(bucket["subjects"])
        if support < min_subjects:
            withheld.append(
                {
                    "theme": _readable(theme_key_value),
                    "reason": "below aggregation floor",
                    "subjects": support,
                    "required": min_subjects,
                }
            )
            continue
        themes.append(
            {
                "theme": _readable(theme_key_value),
                "subjects": support,
                "events": bucket["events"],
                "dwell_hours": round(bucket["dwell_seconds"] / 3600.0, 2),
                "evidence_age_seconds": min(bucket["ages"]) if bucket["ages"] else None,
                "confidence": _confidence(support, bucket["events"], min_subjects),
            }
        )

    themes.sort(key=lambda item: (item["subjects"], item["dwell_hours"]), reverse=True)
    truncated = max(0, len(themes) - max_themes)
    themes = themes[:max_themes]

    status = "ready" if themes else "below_floor"
    decisions = [
        {
            "field": "aggregation_floor",
            "decision": "enforced",
            "reason": f"a theme needs {min_subjects} distinct subjects before it is emitted",
        },
        {
            "field": "subject_identity",
            "decision": "deny",
            "reason": "synthesis consumes opaque subject keys and never emits them",
        },
        {
            "field": "raw_events",
            "decision": "deny",
            "reason": "synthesis reads gated working spheres, never the event ledger",
        },
    ]
    if truncated:
        decisions.append(
            {"field": "themes", "decision": "truncate", "reason": f"{truncated} themes beyond max_themes"}
        )

    return {
        "status": status,
        "generated_at": utc_now().isoformat(),
        "days": days,
        "min_subjects": min_subjects,
        "subjects_seen": len(seen_subjects),
        "themes_emitted": len(themes),
        "themes_withheld": len(withheld),
        "themes": themes,
        "withheld": withheld,
        "decisions": decisions,
    }


def format_synthesis_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Collective context synthesis",
        "",
        f"- subjects seen: **{result['subjects_seen']}**",
        f"- aggregation floor: **{result['min_subjects']}** distinct subjects per theme",
        f"- themes emitted: **{result['themes_emitted']}**, withheld below floor: **{result['themes_withheld']}**",
        "",
    ]
    if result["themes"]:
        lines += [
            "| theme | subjects | events | hours | confidence |",
            "| --- | --- | --- | --- | --- |",
        ]
        for theme in result["themes"]:
            lines.append(
                f"| {theme['theme']} | {theme['subjects']} | {theme['events']} | "
                f"{theme['dwell_hours']} | {theme['confidence']} |"
            )
    else:
        lines.append("_No theme cleared the aggregation floor. That is a valid answer, not an error._")

    if result["withheld"]:
        lines += ["", "## Withheld", ""]
        for item in result["withheld"]:
            lines.append(
                f"- **{item['theme']}** — {item['reason']} "
                f"({item['subjects']}/{item['required']} subjects)"
            )
    return "\n".join(lines) + "\n"
