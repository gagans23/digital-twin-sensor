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

This is a descriptive instrument only. It has no prospective assignment or
pack-exposure ledger. Historical dates cannot establish whether a pack was
delivered, withheld, or used. Reports never infer a treatment comparison.

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
# Retained for callers planning a future prospective protocol, not an effect gate.
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
    return "calendar_even" if block % 2 == 0 else "calendar_odd"


def _cluster_key(event: dict[str, Any]) -> str:
    """What counts as 'the same work'. Artefact identity is the strongest
    available signal without reading content; app is the fallback when the
    artefact label is empty."""
    artifact = str(event.get("artifact") or "").strip().lower()
    return artifact or f"app:{str(event.get('app') or '').strip().lower()}"


@dataclass
class Run:
    """Consecutive attention on one cluster, with the dwell summed.

    The collector samples every few seconds, so a single event never
    represents sustained work. Judging "substantive" on one event's dwell
    made the detector find nothing at all against a real trace of 11,783
    events — the first thing it was pointed at. Work is a run, not an event.
    """

    cluster: str
    start: datetime
    end: datetime
    dwell: float
    artifact: str
    app: str


def build_runs(
    events: list[dict[str, Any]],
    *,
    gap_minutes: float = DEFAULT_GAP_MINUTES,
) -> list[Run]:
    ordered = sorted(
        (e for e in events if e.get("ts_start") and e.get("ts_end")),
        key=lambda e: parse_dt(str(e["ts_start"])),
    )
    gap = timedelta(minutes=gap_minutes)
    runs: list[Run] = []

    for event in ordered:
        cluster = _cluster_key(event)
        start = parse_dt(str(event["ts_start"]))
        end = parse_dt(str(event["ts_end"]))
        dwell = float(event.get("dwell_seconds") or 0.0)

        if runs and runs[-1].cluster == cluster and start - runs[-1].end < gap:
            current = runs[-1]
            current.end = max(current.end, end)
            current.dwell += dwell
            continue

        runs.append(
            Run(
                cluster=cluster,
                start=start,
                end=end,
                dwell=dwell,
                artifact=str(event.get("artifact") or ""),
                app=str(event.get("app") or ""),
            )
        )

    return runs


def find_resume_events(
    events: list[dict[str, Any]],
    *,
    gap_minutes: float = DEFAULT_GAP_MINUTES,
    substantive_seconds: float = DEFAULT_SUBSTANTIVE_SECONDS,
    block_days: int = DEFAULT_BLOCK_DAYS,
    diagnostics: dict[str, int] | None = None,
) -> list[ResumeEvent]:
    """One resume event per interruption episode.

    Three rules stop the count inflating or collapsing. Work is measured as a
    *run* of consecutive attention, not a single sampled event. The task being
    returned to is the last run that was substantive, so a glance before the
    interruption is not mistaken for what someone was doing. And once an
    episode resolves, scanning continues after the resumption, so a pause
    inside the resumed stretch is not charged to the same interruption twice.
    """
    runs = build_runs(events, gap_minutes=gap_minutes)
    if diagnostics is not None:
        diagnostics["runs"] = len(runs)
        diagnostics["substantive_runs"] = sum(1 for r in runs if r.dwell >= substantive_seconds)
    if len(runs) < 2:
        return []

    gap = timedelta(minutes=gap_minutes)
    resumes: list[ResumeEvent] = []
    interruptions = anchored = 0
    index = 1

    while index < len(runs):
        previous = runs[index - 1]
        current = runs[index]

        if current.start - previous.end < gap:
            if previous.dwell >= substantive_seconds and current.cluster != previous.cluster:
                returned = next((offset for offset in range(index + 1, len(runs))
                                 if runs[offset].cluster == previous.cluster and runs[offset].dwell >= substantive_seconds), None)
                if returned is not None and runs[returned].start - current.start >= gap:
                    interruptions += 1
                    anchored += 1
                    resumes.append(ResumeEvent(
                        interrupted_at=previous.end.isoformat(), resumed_at=runs[returned].start.isoformat(),
                        resume_seconds=(runs[returned].start - current.start).total_seconds(),
                        gap_seconds=(runs[returned].start - previous.end).total_seconds(),
                        artifact=previous.artifact, app=previous.app,
                        condition="exposure_unknown", day=current.start.date().isoformat(),
                    ))
                    index = returned + 1
                    continue
            index += 1
            continue

        interruptions += 1

        # What was actually being worked on before the interruption.
        anchor = None
        for candidate in reversed(runs[:index]):
            if candidate.dwell >= substantive_seconds:
                anchor = candidate
                break
        if anchor is None:
            index += 1
            continue

        anchored += 1
        resumed_index = None
        for offset in range(index, len(runs)):
            candidate = runs[offset]
            if candidate.cluster != anchor.cluster:
                continue
            if candidate.dwell < substantive_seconds:
                continue  # a glance, not resumed work
            resumed_index = offset
            break

        if resumed_index is None:
            index += 1
            continue

        resumed_at = runs[resumed_index].start
        resumes.append(
            ResumeEvent(
                interrupted_at=previous.end.isoformat(),
                resumed_at=resumed_at.isoformat(),
                resume_seconds=(resumed_at - current.start).total_seconds(),
                gap_seconds=(current.start - previous.end).total_seconds(),
                artifact=anchor.artifact,
                app=anchor.app,
                condition="exposure_unknown",
                day=current.start.date().isoformat(),
            )
        )
        # The episode is closed; do not recount a pause inside the resumption.
        index = resumed_index + 1

    if diagnostics is not None:
        diagnostics["interruptions"] = interruptions
        diagnostics["interruptions_with_a_known_task"] = anchored
        diagnostics["resumes"] = len(resumes)

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
    diagnostics: dict[str, int] = {}
    resumes = find_resume_events(
        windowed,
        gap_minutes=gap_minutes,
        substantive_seconds=substantive_seconds,
        block_days=block_days,
        diagnostics=diagnostics,
    )

    by_condition: dict[str, list[float]] = {"exposure_unknown": []}
    for resume in resumes:
        by_condition[resume.condition].append(resume.resume_seconds)

    overall = describe([r.resume_seconds for r in resumes])
    conditions = {name: describe(values) for name, values in by_condition.items()}

    caveats = [
        "No prospective assignment or pack exposure was recorded. This report is descriptive; no treatment comparison is valid.",
        "Return delay measures observable activity, not productive resumption or a confirmed outcome.",
        "Single subject, single machine: this is a case study, not a trial.",
        "The operator can see which condition they are in. A tool you can look at "
        "cannot be blinded, and this confound does not shrink with sample size.",
        "Resume events are inferred from attention gaps, not self-reported. A gap "
        "is a proxy for an interruption and will miscount an unattended machine.",
    ]

    comparable = False
    difference = None

    # A zero has to say why it is a zero. The first real run of this study
    # found nothing across 11,783 events and reported it as an empty table,
    # which is indistinguishable from a subject who was never interrupted.
    explanation = None
    if not resumes:
        if not windowed:
            explanation = "No events in the window. Is the sensor running?"
        elif not diagnostics.get("substantive_runs"):
            explanation = (
                f"No run of attention reached {substantive_seconds:.0f}s. The collector "
                "samples in short intervals, so try a lower --substantive-seconds, or "
                "check that dwell is being recorded."
            )
        elif not diagnostics.get("interruptions"):
            explanation = (
                f"No gap longer than {gap_minutes:.0f} min was found. Try a shorter "
                "--gap-minutes, or the trace may be one continuous stretch."
            )
        elif not diagnostics.get("interruptions_with_a_known_task"):
            explanation = (
                "Interruptions were found, but nothing substantive preceded them, "
                "so there was no task to return to."
            )
        else:
            explanation = (
                "Interruptions were found with a known prior task, but the subject "
                "never returned to it substantively. That is a finding, not a bug."
            )

    days_observed = sorted({r.day for r in resumes})
    return {
        "diagnostics": diagnostics,
        "no_resumes_because": explanation,
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
        "study_mode": "descriptive_only",
        "exposure_verified": False,
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

    if report.get("no_resumes_because"):
        lines += ["", f"**No resume events.** {report['no_resumes_because']}", ""]
        diag = report.get("diagnostics") or {}
        if diag:
            lines.append("Detector trace: " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in diag.items()))

    if report["comparison"]:
        lines += [
            "",
            f"**Median difference:** {report['comparison']['median_delta_seconds']}s "
            f"({report['comparison']['direction']}).",
            "",
            report["comparison"]["note"],
        ]
    elif not report["comparable"]:
        lines += ["", "**No comparison reported**: pack exposure was not recorded. More historical events cannot establish it."]

    lines += ["", "## What this cannot tell you", ""]
    lines += [f"- {item}" for item in report["caveats"]]
    return "\n".join(lines) + "\n"
