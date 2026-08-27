from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any


TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]+")


FILTER_CUES = {
    "inverse": ["missing", "absence", "ignored", "neglected", "not looking", "should have"],
    "differential": ["changed", "shift", "unusual", "different", "spike", "drop", "anomaly"],
    "recurrent": ["again", "repeat", "repeated", "revisit", "keeps coming back"],
    "comparative": ["compare", "versus", "vs", "alternative", "evaluation", "choose"],
    "sequential": ["sequence", "after", "before", "workflow", "order", "then"],
    "collective": ["team", "everyone", "group", "cohort", "collective"],
}


def tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(text)}


def select_filters(query: str, profile: dict[str, Any]) -> list[tuple[str, float]]:
    lowered = query.lower()
    selected: list[str] = []
    for name, cues in FILTER_CUES.items():
        if any(cue in lowered for cue in cues):
            selected.append(name)

    if not selected:
        selected.append("proportional")

    if profile.get("v_div", {}).get("kl_short_vs_long", 0) > 0.2 and "differential" not in selected:
        selected.append("differential")

    weight = round(1.0 / len(selected), 4)
    return [(name, weight) for name in selected]


def _artifact_stats(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for event in events:
        artifact = event["artifact"] or event["app"]
        item = stats.setdefault(
            artifact,
            {
                "artifact": artifact,
                "domain": event["domain"],
                "app": event["app"],
                "title": event["title"],
                "dwell_seconds": 0.0,
                "visits": 0,
                "first_seen": event["ts_start"],
                "last_seen": event["ts_end"],
            },
        )
        item["dwell_seconds"] += float(event["dwell_seconds"])
        item["visits"] += 1
        item["last_seen"] = event["ts_end"]
    return stats


def _content_score(query: str, item: dict[str, Any]) -> float:
    query_tokens = tokenize(query)
    text_tokens = tokenize(
        " ".join(
            [
                item.get("artifact", ""),
                item.get("title", ""),
                item.get("app", ""),
                item.get("domain", ""),
            ]
        )
    )
    if not query_tokens:
        return 1.0
    overlap = len(query_tokens & text_tokens)
    soft = sum(1 for token in query_tokens if any(token in text for text in text_tokens))
    return min(1.0, 0.15 + 0.2 * overlap + 0.08 * soft)


def _normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    max_value = max(values.values()) or 1.0
    return {key: value / max_value for key, value in values.items()}


def _attention_scores(
    events: list[dict[str, Any]],
    profile: dict[str, Any],
    filters: list[tuple[str, float]],
) -> tuple[dict[str, float], dict[str, list[str]]]:
    stats = _artifact_stats(events)
    raw_scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)

    dwell = _normalize({key: item["dwell_seconds"] for key, item in stats.items()})
    visits = _normalize({key: item["visits"] for key, item in stats.items()})

    divergence = profile.get("v_div", {}).get("domain_delta", {})
    baseline = profile.get("v_base", {}).get("distribution", {})
    recent = profile.get("v_dom", {}).get("distribution", {})

    transition_involvement: Counter[str] = Counter()
    previous = None
    for event in events:
        current = event["artifact"]
        if previous and previous != current:
            transition_involvement[previous] += 1
            transition_involvement[current] += 1
        previous = current
    transitions = _normalize(dict(transition_involvement))

    for name, filter_weight in filters:
        for artifact, item in stats.items():
            domain = item["domain"]
            if name == "proportional":
                value = dwell.get(artifact, 0.0)
                reason = "high dwell time"
            elif name == "recurrent":
                value = visits.get(artifact, 0.0)
                reason = "repeated revisits"
            elif name == "differential":
                value = max(divergence.get(domain, 0.0), 0.0) * dwell.get(artifact, 0.0)
                reason = f"recent {domain} attention above baseline"
            elif name == "inverse":
                gap = max(baseline.get(domain, 0.0) - recent.get(domain, 0.0), 0.0)
                value = gap * (0.5 + visits.get(artifact, 0.0) / 2)
                reason = f"{domain} has less recent attention than baseline"
            elif name == "comparative":
                value = transitions.get(artifact, 0.0)
                reason = "involved in frequent attention switches"
            elif name == "sequential":
                value = transitions.get(artifact, 0.0) * dwell.get(artifact, 0.0)
                reason = "part of a workflow transition"
            elif name == "collective":
                value = dwell.get(artifact, 0.0)
                reason = "single-user stand-in for cohort attention"
            else:
                value = 0.0
                reason = "unknown filter"

            if value > 0:
                raw_scores[artifact] += filter_weight * value
                reasons[artifact].append(f"{name}: {reason}")

    return dict(raw_scores), dict(reasons)


def retrieve(
    query: str,
    events: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    top_k: int = 8,
) -> dict[str, Any]:
    filters = select_filters(query, profile)
    stats = _artifact_stats(events)
    attention, reasons = _attention_scores(events, profile, filters)

    ranked = []
    for artifact, item in stats.items():
        content = _content_score(query, item)
        attn = attention.get(artifact, 0.0)
        weight = attn * content
        if weight <= 0:
            continue
        ranked.append(
            {
                "artifact": artifact,
                "domain": item["domain"],
                "app": item["app"],
                "dwell_seconds": round(item["dwell_seconds"], 2),
                "visits": item["visits"],
                "first_seen": item["first_seen"],
                "last_seen": item["last_seen"],
                "attention_score": round(attn, 4),
                "content_score": round(content, 4),
                "weight": round(weight, 4),
                "why": reasons.get(artifact, []),
            }
        )

    ranked.sort(key=lambda item: (item["weight"], math.log1p(item["dwell_seconds"])), reverse=True)
    return {
        "query": query,
        "selected_filters": filters,
        "results": ranked[:top_k],
    }


def format_retrieval(result: dict[str, Any]) -> str:
    lines = [f"Query: {result['query']}", ""]
    filters = ", ".join(f"{name}={weight}" for name, weight in result["selected_filters"])
    lines.append(f"Selected attention filters: {filters}")
    lines.append("")
    if not result["results"]:
        lines.append("No evidence matched yet. Collect more events or broaden the query.")
        return "\n".join(lines)

    for index, item in enumerate(result["results"], start=1):
        lines.append(f"{index}. {item['artifact']}")
        lines.append(
            f"   domain={item['domain']} app={item['app']} "
            f"weight={item['weight']} dwell={item['dwell_seconds']}s visits={item['visits']}"
        )
        if item["why"]:
            lines.append(f"   why: {'; '.join(item['why'][:3])}")
    return "\n".join(lines)
