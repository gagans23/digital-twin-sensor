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
    """Stable pseudonym, not anonymization: low-entropy inputs are guessable."""
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
    """Rises with corroboration across people, not with volume from one person.

    PROVENANCE: the 0.65/0.35 split is a hand-chosen prior, not a result. It is
    not taken from any paper and it has not been fitted against labelled data,
    because no labelled data exists yet — that is what the feedback-capture gap
    in docs/UNDER_THE_HOOD.md is about. The only defensible claim is directional:
    breadth is weighted above depth so that one prolific subject cannot
    manufacture a theme alone (see tests/test_synthesis.py). Treat the number as
    a placeholder awaiting calibration, and do not cite it as a finding.

    The aggregation floor it sits behind is a different matter: count-based
    k-anonymity is standard (Sweeney, 2002), though a count floor is a floor,
    not a proof, and it does not defend against repeated differencing attacks.
    """
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
            if sphere.get("sensitivity") == "high" or sphere.get("gate_mode", "allowed") != "allowed":
                continue
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
                    "reason": "below aggregation floor",
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
                f"- Topic withheld: {item['reason']} (minimum {item['required']} subjects)."
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Secure path. See docs/adr/0012 and digital_twin_sensor/aggregation.py.
#
# `synthesize_collective` above requires the caller to hold every subject's
# spheres in the clear. The floor it applies protects the output; nothing
# protected the input. Everything below takes cohort totals that were summed
# under masks instead, so no readable per-subject contribution ever exists at
# the aggregator.
# ---------------------------------------------------------------------------

def theme_of_sphere(sphere: dict[str, Any]) -> str | None:
    """Map a local sphere onto a declared theme id, or nothing.

    Deliberately conservative: an unmapped sphere contributes nothing rather
    than inventing a bucket. Undercounting is recoverable by declaring another
    theme; counting something nobody declared is not.
    """
    domain = str(sphere.get("domain") or "").strip().lower()
    task = f"{sphere.get('task') or ''} {sphere.get('label') or ''}".lower()

    if domain == "coding":
        if any(word in task for word in ("review", "pull request", "diff", "merge")):
            return "coding:review"
        if any(word in task for word in ("bug", "debug", "error", "failure", "trace", "log")):
            return "coding:debugging"
        return "coding:implementation"
    if domain == "operations":
        if any(word in task for word in ("incident", "alert", "outage", "page")):
            return "operations:incident"
        return "operations:runbook"
    if domain in {"analysis", "data"}:
        return "analysis:document" if "doc" in task or "policy" in task or "spec" in task else "analysis:data"
    if domain == "writing":
        return "writing:drafting"
    if domain in {"communication", "email", "chat"}:
        return "communication:meeting" if any(w in task for w in ("call", "meet", "zoom", "standup")) else "communication:async"
    if domain in {"planning", "project"}:
        return "planning:coordination"
    if domain in {"research", "learning"}:
        return "learning:research"
    return None


def synthesize_secure(
    totals: list[int],
    vocabulary: Any,
    *,
    cohort_size: int,
    min_subjects: int = DEFAULT_MIN_SUBJECTS,
    max_themes: int = DEFAULT_MAX_THEMES,
    epsilon: float | None = None,
    days: int = 14,
) -> dict[str, Any]:
    """Fold masked cohort totals into themes above the floor.

    Takes the output of `aggregation.secure_sum` — counts of how many cohort
    members touched each declared theme — and never anything per-subject.

    Confidence is a Wilson interval on the proportion of the cohort, not a
    weighted score. The uncertainty is a property of the count and the cohort
    size, so it is derived; ADR 0008's invented weights are not needed on this
    path and are not used.

    `epsilon`, when set, adds discrete Laplace noise at the aggregator. That is
    central DP and it assumes the aggregator is honest about adding it. At team
    scale it is usually the wrong trade: the noise needed for a meaningful
    epsilon swamps a cohort of ten, and secure aggregation alone is the stronger
    practical protection. Left off by default for that reason.
    """
    from .aggregation import discrete_laplace, wilson_interval  # noqa: PLC0415

    if min_subjects < 2:
        raise ValueError("min_subjects must be at least 2; a floor of 1 is not a floor")
    if cohort_size < min_subjects:
        raise ValueError(
            f"cohort of {cohort_size} cannot clear a floor of {min_subjects}; "
            "publishing from it would be a floor in name only"
        )
    if len(totals) != len(vocabulary):
        raise ValueError("totals do not match the declared vocabulary width")

    scale = (1.0 / epsilon) if epsilon and epsilon > 0 else 0.0
    themes: list[dict[str, Any]] = []
    withheld = 0

    for position, theme_id in enumerate(vocabulary.themes):
        support = int(totals[position])
        if scale:
            support = max(0, support + discrete_laplace(scale))
        if support < min_subjects:
            withheld += 1
            continue
        low, high = wilson_interval(min(support, cohort_size), cohort_size)
        themes.append(
            {
                "theme": theme_id,
                "description": vocabulary.descriptions.get(theme_id, ""),
                "subjects": support,
                "share_of_cohort": round(min(support, cohort_size) / cohort_size, 3),
                "confidence_interval": [low, high],
            }
        )

    themes.sort(key=lambda item: item["subjects"], reverse=True)
    truncated = max(0, len(themes) - max_themes)
    themes = themes[:max_themes]

    # The count of withheld themes is itself a signal about a small cohort, so
    # it is reported as a band rather than an exact figure.
    if withheld == 0:
        withheld_band = "none"
    elif withheld <= 2:
        withheld_band = "1-2"
    elif withheld <= 5:
        withheld_band = "3-5"
    else:
        withheld_band = "6+"

    return {
        "status": "ready" if themes else "below_floor",
        "path": "secure-aggregation",
        "generated_at": utc_now().isoformat(),
        "days": days,
        "cohort_size": cohort_size,
        "min_subjects": min_subjects,
        "vocabulary_version": vocabulary.version,
        "vocabulary_digest": vocabulary.digest,
        "epsilon": epsilon,
        "themes_emitted": len(themes),
        "themes_withheld_band": withheld_band,
        "themes": themes,
        "decisions": [
            {
                "field": "per_subject_contributions",
                "decision": "deny",
                "reason": "contributions are masked; the aggregator never holds a readable per-subject vector",
            },
            {
                "field": "theme_vocabulary",
                "decision": "allow",
                "reason": f"{len(vocabulary)} declared themes, digest {vocabulary.digest}; undeclared work cannot be counted",
            },
            {
                "field": "aggregation_floor",
                "decision": "enforced",
                "reason": f"a theme needs {min_subjects} distinct subjects before it is emitted",
            },
            {
                "field": "withheld_count",
                "decision": "generalize",
                "reason": "an exact suppression count is itself disclosive on a small cohort",
            },
            {
                "field": "differential_privacy",
                "decision": "allow" if epsilon else "deny",
                "reason": (
                    f"central DP noise at epsilon={epsilon}, added by the aggregator"
                    if epsilon
                    else "no noise: at team scale it costs more signal than it buys, and secure aggregation is the stronger protection here"
                ),
            },
        ]
        + ([{"field": "themes", "decision": "truncate", "reason": f"{truncated} themes beyond max_themes"}] if truncated else []),
    }
