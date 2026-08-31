"""Measure task-resume time from the attention trace.

`docs/VALIDATION.md` V2 records the most important thing this project asserts
and has never measured: whether a context pack shortens the time to get back
into a task after an interruption. The claim has been sitting in the README and
in a published essay marked untested, which is honest but not progress.

This module makes the measurement collect itself. It reads the local event store
and derives, without any extra tooling or self-reporting:

    interruption   a gap in attention longer than `gap_minutes`, or a switch to
                   an unrelated artefact that lasts that long
    resume         the first event after that gap that returns to the artefact
                   cluster the subject was on before it
    resume_seconds the interval from the end of the interruption to the first
                   *substantive* return — an event on the prior cluster lasting
                   at least `substantive_seconds`, so a glance at a window that
                   is immediately abandoned does not count as resuming work

Condition assignment is deterministic and recorded per event: alternating
day-length blocks, derived from the ordinal date, so which condition applied on
a given day cannot be chosen after seeing the result. The operator still knows
which block they are in — a tool you can see cannot be blinded — and that
confound is reported in the output rather than buried.

Everything runs locally against the existing store. Nothing new is collected,
nothing leaves the machine.

    digital-twin-sensor resume-study --days 14
    digital-twin-sensor resume-study --days 14 --format json
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .store import filter_window, parse_dt

# A pause shorter than this is thinking, not an interruption.
DEFAULT_GAP_MINUTES = 15.0
# A return shorter than this is a glance, not resumed work.
DEFAULT_SUBSTANTIVE_SECONDS = 60.0
# Blocks alternate every N days so both conditions see the same weekday mix
# over a fortnight.
DEFAULT_BLOCK_DAYS = 1
# Below this, report the distribution but refuse to compare conditions.
MIN_EVENTS_PER_CONDITION = 10


@dataclass
class ResumeEvent:
    interrupted_at: str
    resumed_at: str
    resume_seconds: float
    gap_seconds: float
    artifact: str
    app: str
    condition: str
    day: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "interrupted_at": self.interrupted_at,
            "resumed_at": self.resumed_at,
            "resume_seconds": round(self.resume_seconds, 1),
            "gap_seconds": round(self.gap_seconds, 1),
            "artifact": self.artifact,
            "app": self.app,
            "condition": self.condition,
            "day": self.day,
        }


@dataclass
class Distribution:
    n: int = 0
    median: float | None = None
    p25: float | None = None
    p75: float | None = None
    p90: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "median_seconds": self.median,
            "p25_seconds": self.p25,
            "p75_seconds": self.p75,
            "p90_seconds": self.p90,
            "min_seconds": self.minimum,
            "max_seconds": self.maximum,
        }


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank, so a small sample is not smoothed into a shape it does
    not have."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def describe(values: list[float]) -> Distribution:
    """Resume time is long-tailed and the tail is the interesting part, so the
    report is a distribution. A mean would hide exactly what matters."""
    if not values:
        return Distribution()
    return Distribution(
        n=len(values),
        median=round(statistics.median(values), 1),
        p25=round(_percentile(values, 0.25), 1),
        p75=round(_percentile(values, 0.75), 1),
        p90=round(_percentile(values, 0.90), 1),
        minimum=round(min(values), 1),
        maximum=round(max(values), 1),
        values=values,
    )


def assign_condition(moment: datetime, block_days: int = DEFAULT_BLOCK_DAYS) -> str:
    """Deterministic from the date alone, so a block cannot be reassigned after
    the fact to flatter a result."""
    block = moment.toordinal() // max(1, block_days)
    return "pack_available" if block % 2 == 0 else "pack_withheld"


def _cluster_key(event: dict[str, Any]) -> str:
    """What counts as 'the same work'. Artefact identity is the strongest
    available signal without reading content; app is the fallback when the
    artefact label is empty."""
    artifact = str(event.get("artifact") or "").strip().lower()
    return artifact or f"app:{str(event.get('app') or '').strip().lower()}"


def find_resume_events(
    events: list[dict[str, Any]],
    *,
    gap_minutes: float = DEFAULT_GAP_MINUTES,
    substantive_seconds: float = DEFAULT_SUBSTANTIVE_SECONDS,
    block_days: int = DEFAULT_BLOCK_DAYS,
) -> list[ResumeEvent]:
    """One resume event per interruption episode.

    Two rules stop the count inflating. The task being returned to is the last
    *substantive* activity before the gap, not merely the last event — a
    five-second glance is not what the subject was doing. And once an episode
    resolves, scanning continues after the resumption, so a pause inside the
    resumed stretch is not charged to the same interruption twice.
    """
    ordered = sorted(
        (e for e in events if e.get("ts_start") and e.get("ts_end")),
        key=lambda e: parse_dt(str(e["ts_start"])),
    )
    if len(ordered) < 2:
        return []

    gap = timedelta(minutes=gap_minutes)
    resumes: list[ResumeEvent] = []
    index = 1

    while index < len(ordered):
        previous = ordered[index - 1]
        current = ordered[index]
        previous_end = parse_dt(str(previous["ts_end"]))
        current_start = parse_dt(str(current["ts_start"]))

        if current_start - previous_end < gap:
            index += 1
            continue

        # What was actually being worked on before the interruption.
        anchor = None
        for candidate in reversed(ordered[:index]):
            if float(candidate.get("dwell_seconds") or 0.0) >= substantive_seconds:
                anchor = candidate
                break
        if anchor is None:
            index += 1
            continue

        target = _cluster_key(anchor)
        resumed_index = None
        for offset, candidate in enumerate(ordered[index:], start=index):
            if _cluster_key(candidate) != target:
                continue
            if float(candidate.get("dwell_seconds") or 0.0) < substantive_seconds:
                continue  # a glance, not resumed work
            resumed_index = offset
            break

        if resumed_index is None:
            index += 1
            continue

        resumed_at = parse_dt(str(ordered[resumed_index]["ts_start"]))
        resumes.append(
            ResumeEvent(
                interrupted_at=previous_end.isoformat(),
                resumed_at=resumed_at.isoformat(),
                resume_seconds=(resumed_at - current_start).total_seconds(),
                gap_seconds=(current_start - previous_end).total_seconds(),
                artifact=str(anchor.get("artifact") or ""),
                app=str(anchor.get("app") or ""),
                condition=assign_condition(current_start, block_days),
                day=current_start.date().isoformat(),
            )
        )
        # The episode is closed; do not recount a pause inside the resumption.
        index = resumed_index + 1

    return resumes


def run_resume_study(
    events: list[dict[str, Any]],
    *,
    days: int = 14,
    gap_minutes: float = DEFAULT_GAP_MINUTES,
    substantive_seconds: float = DEFAULT_SUBSTANTIVE_SECONDS,
    block_days: int = DEFAULT_BLOCK_DAYS,
) -> dict[str, Any]:
    windowed = filter_window(events, days)
    resumes = find_resume_events(
        windowed,
        gap_minutes=gap_minutes,
        substantive_seconds=substantive_seconds,
        block_days=block_days,
    )

    by_condition: dict[str, list[float]] = {"pack_available": [], "pack_withheld": []}
    for resume in resumes:
        by_condition[resume.condition].append(resume.resume_seconds)

    overall = describe([r.resume_seconds for r in resumes])
    conditions = {name: describe(values) for name, values in by_condition.items()}

    caveats = [
        "Single subject, single machine: this is a case study, not a trial.",
        "The operator can see which condition they are in. A tool you can look at "
        "cannot be blinded, and this confound does not shrink with sample size.",
        "Resume events are inferred from attention gaps, not self-reported. A gap "
        "is a proxy for an interruption and will miscount an unattended machine.",
    ]

    comparable = all(
        conditions[name].n >= MIN_EVENTS_PER_CONDITION for name in ("pack_available", "pack_withheld")
    )
    if not comparable:
        caveats.insert(
            0,
            f"Fewer than {MIN_EVENTS_PER_CONDITION} resume events in at least one "
            "condition. The distributions are reported; the comparison is not, "
            "because it would not mean anything yet.",
        )

    difference = None
    if comparable:
        available = conditions["pack_available"].median
        withheld = conditions["pack_withheld"].median
        if available is not None and withheld is not None:
            difference = {
                "median_delta_seconds": round(available - withheld, 1),
                "direction": "faster with pack" if available < withheld else "slower with pack",
                "note": "A median difference on one subject is a signal to investigate, "
                "never a result to publish as an effect.",
            }

    days_observed = sorted({r.day for r in resumes})
    return {
        "window_days": days,
        "gap_minutes": gap_minutes,
        "substantive_seconds": substantive_seconds,
        "block_days": block_days,
        "events_considered": len(windowed),
        "resume_events": len(resumes),
        "days_with_data": len(days_observed),
        "first_day": days_observed[0] if days_observed else None,
        "last_day": days_observed[-1] if days_observed else None,
        "overall": overall.to_dict(),
        "conditions": {name: dist.to_dict() for name, dist in conditions.items()},
        "comparison": difference,
        "comparable": comparable,
        "caveats": caveats,
        "events": [r.to_dict() for r in resumes],
    }


def format_resume_study_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Task-resume study",
        "",
        f"- window: **{report['window_days']} days**, "
        f"events considered: **{report['events_considered']}**",
        f"- resume events detected: **{report['resume_events']}** "
        f"across **{report['days_with_data']}** days",
    ]
    if report["first_day"]:
        lines.append(f"- observed: {report['first_day']} to {report['last_day']}")
    lines += [
        f"- interruption threshold: {report['gap_minutes']} min, "
        f"substantive return: {report['substantive_seconds']}s",
        "",
        "| group | n | median | p25 | p75 | p90 | max |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    def row(label: str, dist: dict[str, Any]) -> str:
        if not dist["n"]:
            return f"| {label} | 0 | — | — | — | — | — |"
        return (
            f"| {label} | {dist['n']} | {dist['median_seconds']}s | {dist['p25_seconds']}s | "
            f"{dist['p75_seconds']}s | {dist['p90_seconds']}s | {dist['max_seconds']}s |"
        )

    lines.append(row("all resumes", report["overall"]))
    for name, dist in report["conditions"].items():
        lines.append(row(name.replace("_", " "), dist))

    if report["comparison"]:
        lines += [
            "",
            f"**Median difference:** {report['comparison']['median_delta_seconds']}s "
            f"({report['comparison']['direction']}).",
            "",
            report["comparison"]["note"],
        ]
    elif not report["comparable"]:
        lines += ["", "**No comparison reported** — not enough resume events yet."]

    lines += ["", "## What this cannot tell you", ""]
    lines += [f"- {item}" for item in report["caveats"]]
    return "\n".join(lines) + "\n"
