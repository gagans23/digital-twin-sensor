"""Compare a harness run against a committed baseline.

A pass/fail gate answers one question: is the context good enough right now.
It cannot see a system that is quietly getting worse while staying above the
floor — recall drifting 0.98 to 0.80 over a quarter reads as green every single
run. That drift is the failure mode the essay this repository accompanies claims
nobody measures, so measuring it here seemed like the least I could do.

The baseline is a committed JSON file of the last accepted scores. Every run is
diffed against it and a regression beyond tolerance fails the build, whatever
the absolute score. Improvements never fail; they print, and the baseline is
refreshed deliberately:

    digital-twin-sensor harness --baseline harness/baseline.json
    digital-twin-sensor harness --update-baseline harness/baseline.json

Noise is not drift, so a tolerance keeps small fluctuations from crying wolf.
The harness is deterministic today, which makes the tolerance nearly free, but
scenarios that sample will need it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Recall may fall this far below baseline before it counts as a regression.
RECALL_TOLERANCE = 0.02
# Noise may rise this far above baseline.
NOISE_TOLERANCE = 0.05
# A pack growing much larger is usually the gate admitting more than it did.
PACK_GROWTH_TOLERANCE = 0.25


def summarise(report: dict[str, Any]) -> dict[str, Any]:
    """The subset of a run worth holding still. Timestamps are excluded on
    purpose: a baseline that changes every run is not a baseline."""
    return {
        "mean_recall": report["mean_recall"],
        "mean_noise_ratio": report["mean_noise_ratio"],
        "leak_count": report["leak_count"],
        "scenarios": {
            result["name"]: {
                "recall": result["recall"],
                "noise_ratio": result["noise_ratio"],
                "leaks": len(result["leaks"]),
                "pack_chars": result["pack_chars"],
                "gate_counts": result["gate_counts"],
            }
            for result in report["results"]
        },
    }


def write_baseline(report: dict[str, Any], path: Path) -> dict[str, Any]:
    payload = summarise(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare(report: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Regressions fail the build; improvements and new scenarios only inform."""
    current = summarise(report)
    regressions: list[str] = []
    improvements: list[str] = []
    notes: list[str] = []

    if current["leak_count"] > baseline.get("leak_count", 0):
        regressions.append(
            f"leak count rose {baseline.get('leak_count', 0)} -> {current['leak_count']}"
        )

    base_recall = float(baseline.get("mean_recall", 0.0))
    if current["mean_recall"] < base_recall - RECALL_TOLERANCE:
        regressions.append(f"mean recall {base_recall} -> {current['mean_recall']}")
    elif current["mean_recall"] > base_recall:
        improvements.append(f"mean recall {base_recall} -> {current['mean_recall']}")

    base_noise = float(baseline.get("mean_noise_ratio", 0.0))
    if current["mean_noise_ratio"] > base_noise + NOISE_TOLERANCE:
        regressions.append(f"mean noise {base_noise} -> {current['mean_noise_ratio']}")

    base_scenarios = baseline.get("scenarios", {})
    for name, now in current["scenarios"].items():
        before = base_scenarios.get(name)
        if before is None:
            notes.append(f"{name}: new scenario, not in baseline")
            continue

        if now["leaks"] > before.get("leaks", 0):
            regressions.append(f"{name}: leaks {before.get('leaks', 0)} -> {now['leaks']}")
        if now["recall"] < float(before.get("recall", 0.0)) - RECALL_TOLERANCE:
            regressions.append(f"{name}: recall {before['recall']} -> {now['recall']}")
        if now["noise_ratio"] > float(before.get("noise_ratio", 0.0)) + NOISE_TOLERANCE:
            regressions.append(f"{name}: noise {before['noise_ratio']} -> {now['noise_ratio']}")

        # A gate that stops denying is a regression even when recall improves.
        before_deny = int((before.get("gate_counts") or {}).get("deny", 0))
        now_deny = int((now.get("gate_counts") or {}).get("deny", 0))
        if now_deny < before_deny:
            regressions.append(f"{name}: gate denials {before_deny} -> {now_deny}")

        before_chars = int(before.get("pack_chars", 0) or 0)
        if before_chars and now["pack_chars"] > before_chars * (1 + PACK_GROWTH_TOLERANCE):
            regressions.append(
                f"{name}: pack grew {before_chars} -> {now['pack_chars']} chars "
                "(is the gate admitting more than it was?)"
            )

    for name in base_scenarios:
        if name not in current["scenarios"]:
            regressions.append(f"{name}: scenario disappeared from the golden set")

    return {
        "ok": not regressions,
        "regressions": regressions,
        "improvements": improvements,
        "notes": notes,
        "current": current,
    }


def format_comparison(comparison: dict[str, Any]) -> str:
    lines = ["", "## Baseline comparison", ""]
    if comparison["regressions"]:
        lines.append("**REGRESSION** against the committed baseline:")
        lines += [f"- {item}" for item in comparison["regressions"]]
    else:
        lines.append("No regression against the committed baseline.")
    if comparison["improvements"]:
        lines += ["", "Improved (baseline not updated automatically):"]
        lines += [f"- {item}" for item in comparison["improvements"]]
    if comparison["notes"]:
        lines += ["", "Notes:"]
        lines += [f"- {item}" for item in comparison["notes"]]
    return "\n".join(lines) + "\n"
