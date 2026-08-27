from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean, median
from typing import Any

from .store import parse_dt


def _distribution(counter: dict[str, float]) -> dict[str, float]:
    total = sum(counter.values())
    if total <= 0:
        return {}
    return {key: round(value / total, 4) for key, value in sorted(counter.items())}


def _entropy(counter: dict[str, float]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    value = 0.0
    for count in counter.values():
        p = count / total
        if p > 0:
            value -= p * math.log2(p)
    return round(value, 4)


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    domains = set(p) | set(q)
    eps = 1e-6
    value = 0.0
    for domain in domains:
        pv = p.get(domain, eps)
        qv = q.get(domain, eps)
        value += pv * math.log((pv + eps) / (qv + eps))
    return round(value, 4)


def _domain_dwell(events: list[dict[str, Any]]) -> dict[str, float]:
    dwell: dict[str, float] = defaultdict(float)
    for event in events:
        dwell[event["domain"]] += float(event["dwell_seconds"])
    return dict(dwell)


def _transition_counter(events: list[dict[str, Any]]) -> Counter[str]:
    transitions: Counter[str] = Counter()
    previous = None
    for event in events:
        current = event["domain"]
        if previous and previous != current:
            transitions[f"{previous} -> {current}"] += 1
        previous = current
    return transitions


def _hour_histogram(events: list[dict[str, Any]]) -> dict[str, int]:
    hours: Counter[str] = Counter()
    for event in events:
        hour = parse_dt(event["ts_start"]).hour
        hours[f"{hour:02d}:00"] += 1
    return dict(sorted(hours.items()))


def build_digital_twin_signature(
    events: list[dict[str, Any]],
    *,
    short_days: int = 5,
    long_days: int = 14,
) -> dict[str, Any]:
    if not events:
        return {
            "status": "empty",
            "message": "No events yet. Run the sensor for a few hours, then rebuild the profile.",
        }

    events = sorted(events, key=lambda item: item["ts_start"])
    last_ts = parse_dt(events[-1]["ts_start"])
    short_cutoff = last_ts.timestamp() - short_days * 86400
    long_cutoff = last_ts.timestamp() - long_days * 86400

    short_events = [
        event for event in events if parse_dt(event["ts_start"]).timestamp() >= short_cutoff
    ]
    long_events = [
        event for event in events if parse_dt(event["ts_start"]).timestamp() >= long_cutoff
    ]

    short_domain_dwell = _domain_dwell(short_events)
    long_domain_dwell = _domain_dwell(long_events)
    short_dist = _distribution(short_domain_dwell)
    long_dist = _distribution(long_domain_dwell)

    dwell_values = [float(event["dwell_seconds"]) for event in short_events]
    artifact_visits = Counter(event["artifact"] for event in short_events)
    app_visits = Counter(event["app"] for event in short_events)
    transitions = _transition_counter(short_events)

    domain_delta = {
        domain: round(short_dist.get(domain, 0.0) - long_dist.get(domain, 0.0), 4)
        for domain in sorted(set(short_dist) | set(long_dist))
    }

    responsibility = [
        {"domain": domain, "share": share}
        for domain, share in sorted(long_dist.items(), key=lambda item: item[1], reverse=True)
        if share >= 0.15
    ][:5]

    return {
        "status": "ready",
        "event_count": len(events),
        "window": {
            "short_days": short_days,
            "long_days": long_days,
            "first_event": events[0]["ts_start"],
            "last_event": events[-1]["ts_start"],
        },
        "v_dom": {
            "description": "Domain attention: where recent attention is concentrated.",
            "distribution": short_dist,
            "dwell_seconds_by_domain": {
                key: round(value, 2) for key, value in sorted(short_domain_dwell.items())
            },
        },
        "v_rhythm": {
            "description": "Behavioral rhythm: dwell, revisit, transitions, and active-hour patterns.",
            "mean_dwell_seconds": round(mean(dwell_values), 2) if dwell_values else 0.0,
            "median_dwell_seconds": round(median(dwell_values), 2) if dwell_values else 0.0,
            "revisit_rate": round(
                sum(count - 1 for count in artifact_visits.values() if count > 1)
                / max(len(short_events), 1),
                4,
            ),
            "domain_transition_entropy": _entropy(dict(transitions)),
            "active_hour_histogram": _hour_histogram(short_events),
            "top_transitions": transitions.most_common(10),
        },
        "v_base": {
            "description": "Baseline: longer-window per-domain normal behavior.",
            "distribution": long_dist,
            "dwell_seconds_by_domain": {
                key: round(value, 2) for key, value in sorted(long_domain_dwell.items())
            },
        },
        "v_resp": {
            "description": "Responsibility profile inferred from repeated attention patterns.",
            "likely_owned_domains": responsibility,
            "top_apps": app_visits.most_common(10),
        },
        "v_div": {
            "description": "Short-vs-long divergence: how current attention differs from baseline.",
            "domain_delta": domain_delta,
            "kl_short_vs_long": _kl_divergence(short_dist, long_dist),
        },
    }
