"""Evaluation harness for context packs.

Unit tests prove a function returns what it was told to return. They cannot tell
you whether the context this system hands an agent is *good* — relevant enough to
be useful, and tight enough to be safe. That is a measurement problem, and it needs
a golden set plus metrics that run the same way every time.

This module runs scenarios end to end: synthetic attention traces in, gated context
pack out, scored against expectations. It is deliberately boring and deterministic.
Leakage is the metric that matters most: a canary that reaches an export is a hard
failure regardless of how good the recall was.

    digital-twin-sensor harness
    digital-twin-sensor harness --format json --fail-under 0.8
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG
from .context_pack import build_context_pack, format_context_pack_markdown
from .query import retrieve
from .redaction import redact_text
from .store import utc_now
from .twin import build_digital_twin_signature
from .working_spheres import build_working_spheres

SCENARIO_PATH = Path(__file__).resolve().parents[1] / "harness" / "scenarios.json"

# A canary that survives to an export is a leak, whatever the recall score says.
LEAK_WEIGHT = 1.0
DEFAULT_FAIL_UNDER = 0.75


@dataclass
class ScenarioResult:
    name: str
    description: str
    recall: float
    noise_ratio: float
    leaks: list[str] = field(default_factory=list)
    evidence_age_seconds: int = 0
    pack_chars: int = 0
    gate_counts: dict[str, int] = field(default_factory=dict)
    status: str = "ok"
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.leaks and self.recall >= self.expected_recall

    expected_recall: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "passed": self.passed,
            "recall": round(self.recall, 4),
            "noise_ratio": round(self.noise_ratio, 4),
            "leaks": self.leaks,
            "evidence_age_seconds": self.evidence_age_seconds,
            "pack_chars": self.pack_chars,
            "gate_counts": self.gate_counts,
            "status": self.status,
            "expected_recall": self.expected_recall,
            "notes": self.notes,
        }


def _event(
    index: int,
    spec: dict[str, Any],
    config: dict[str, Any],
    *,
    minutes_ago: float,
    apply_collection_redaction: bool,
) -> dict[str, Any]:
    """Build one stored-shape event, optionally passing the title through the
    same masking the collector applies before anything is written to disk."""
    raw_title = str(spec.get("title", "untitled"))
    findings: dict[str, int] = {}
    title = raw_title
    if apply_collection_redaction:
        result = redact_text(raw_title, config)
        title = result.text
        findings = dict(result.findings)

    start = utc_now() - timedelta(minutes=minutes_ago)
    dwell = float(spec.get("dwell_seconds", 90.0))
    return {
        "id": index,
        "subject_id": config.get("subject_id", "harness"),
        "source": "harness",
        "app": str(spec.get("app", "Kiro")),
        "title": title,
        "artifact": title or str(spec.get("app", "Kiro")),
        "domain": str(spec.get("domain", "coding")),
        "action": "focus",
        "ts_start": start.isoformat(),
        "ts_end": (start + timedelta(seconds=dwell)).isoformat(),
        "dwell_seconds": dwell,
        "metadata": {
            "collector_version": "harness-v1",
            "redaction_findings": findings,
            "privacy": "no_keystrokes_no_screenshots_no_clipboard",
        },
    }


def build_events(scenario: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    apply_redaction = bool(scenario.get("apply_collection_redaction", True))
    age_minutes = float(scenario.get("age_minutes", 30.0))
    step = float(scenario.get("step_minutes", 12.0))
    events: list[dict[str, Any]] = []
    index = 1
    for spec in scenario.get("events", []):
        for _ in range(int(spec.get("repeat", 1))):
            events.append(
                _event(
                    index,
                    spec,
                    config,
                    minutes_ago=age_minutes + index * step,
                    apply_collection_redaction=apply_redaction,
                )
            )
            index += 1
    return events


def _serialise_pack(pack: dict[str, Any]) -> str:
    """Everything a target could conceivably read, in one string."""
    try:
        markdown = format_context_pack_markdown(pack)
    except Exception:  # a malformed pack must not hide a leak
        markdown = ""
    return f"{markdown}\n{json.dumps(pack, default=str)}"


def _gate_counts(pack: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in pack.get("decisions", []) or []:
        key = str(decision.get("decision", "unknown"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _evidence_age(pack: dict[str, Any]) -> int:
    ages = []
    for key in ("last_age_seconds", "evidence_age_seconds"):
        value = pack.get(key)
        if isinstance(value, (int, float)):
            ages.append(int(value))
    sphere = pack.get("working_sphere") or {}
    if isinstance(sphere, dict) and isinstance(sphere.get("last_age_seconds"), (int, float)):
        ages.append(int(sphere["last_age_seconds"]))
    return max(ages) if ages else 0


def run_scenario(scenario: dict[str, Any], config: dict[str, Any] | None = None) -> ScenarioResult:
    config = json.loads(json.dumps(config or DEFAULT_CONFIG))
    for key, value in (scenario.get("config_overrides") or {}).items():
        config[key] = value

    events = build_events(scenario, config)
    days = int(scenario.get("days", 14))
    activities = build_working_spheres(events, config, days=days)
    pack = build_context_pack(
        events,
        config,
        days=days,
        purpose=str(scenario.get("purpose", "coding")),
        target=str(scenario.get("target", "kiro")),
        activities=activities,
    )
    blob = _serialise_pack(pack)
    lowered = blob.lower()

    must = [str(item) for item in scenario.get("must_surface", [])]
    found = [item for item in must if item.lower() in lowered]
    recall = (len(found) / len(must)) if must else 1.0

    leaks = [item for item in scenario.get("must_not_surface", []) if str(item).lower() in lowered]

    expected = {str(item).lower() for item in scenario.get("expected_artifacts", [])}
    artifacts = []
    sphere = pack.get("working_sphere") or {}
    if isinstance(sphere, dict):
        artifacts = [str(a.get("name", "")).lower() for a in (sphere.get("artifacts") or [])]
    noise = [a for a in artifacts if expected and a not in expected]
    noise_ratio = (len(noise) / len(artifacts)) if artifacts else 0.0

    notes: list[str] = []
    missing = [item for item in must if item not in found]
    if missing:
        notes.append(f"did not surface: {', '.join(missing)}")
    if leaks:
        notes.append(f"LEAK — canary reached the export: {', '.join(leaks)}")

    # Optional retrieval probe against the same trace.
    probe = scenario.get("query")
    if probe:
        profile = build_digital_twin_signature(events)
        ranked = retrieve(str(probe), events, profile, top_k=5)
        top = [str(item.get("artifact", "")).lower() for item in ranked.get("results", [])[:3]]
        want = str(scenario.get("query_expects", "")).lower()
        if want and not any(want in item for item in top):
            notes.append(f"retrieval probe missed: {scenario['query_expects']!r} not in top 3")

    return ScenarioResult(
        name=str(scenario.get("name", "unnamed")),
        description=str(scenario.get("description", "")),
        recall=recall,
        noise_ratio=noise_ratio,
        leaks=leaks,
        evidence_age_seconds=_evidence_age(pack),
        pack_chars=len(blob),
        gate_counts=_gate_counts(pack),
        status=str(pack.get("status", "unknown")),
        expected_recall=float(scenario.get("expected_recall", 0.0)),
        notes=notes,
    )


def load_scenarios(path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path else SCENARIO_PATH
    if not target.exists():
        raise FileNotFoundError(f"no scenario file at {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    return list(payload.get("scenarios", []))


def run_harness(
    scenarios: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    *,
    fail_under: float = DEFAULT_FAIL_UNDER,
) -> dict[str, Any]:
    scenarios = scenarios if scenarios is not None else load_scenarios()
    results = [run_scenario(scenario, config) for scenario in scenarios]

    total_leaks = sum(len(r.leaks) for r in results)
    mean_recall = round(sum(r.recall for r in results) / len(results), 4) if results else 0.0
    mean_noise = round(sum(r.noise_ratio for r in results) / len(results), 4) if results else 0.0
    failed = [r.name for r in results if not r.passed]

    return {
        "generated_at": utc_now().isoformat(),
        "scenarios": len(results),
        "passed": len(results) - len(failed),
        "failed": failed,
        "mean_recall": mean_recall,
        "mean_noise_ratio": mean_noise,
        "leak_count": total_leaks,
        "fail_under": fail_under,
        "ok": total_leaks == 0 and mean_recall >= fail_under and not failed,
        "results": [r.to_dict() for r in results],
    }


def format_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Context pack harness",
        "",
        f"- scenarios: **{report['scenarios']}**, passed: **{report['passed']}**",
        f"- mean recall: **{report['mean_recall']}** (floor {report['fail_under']})",
        f"- mean noise ratio: **{report['mean_noise_ratio']}**",
        f"- leaks: **{report['leak_count']}**",
        f"- verdict: **{'PASS' if report['ok'] else 'FAIL'}**",
        "",
        "| scenario | recall | noise | leaks | age (s) | chars | status |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["results"]:
        mark = "" if r["passed"] else " ⚠"
        lines.append(
            f"| {r['name']}{mark} | {r['recall']} | {r['noise_ratio']} | "
            f"{len(r['leaks'])} | {r['evidence_age_seconds']} | {r['pack_chars']} | {r['status']} |"
        )
    notes = [(r["name"], n) for r in report["results"] for n in r["notes"]]
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- **{name}** — {note}" for name, note in notes]
    return "\n".join(lines) + "\n"
