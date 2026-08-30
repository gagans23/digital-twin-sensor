from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .store import filter_window, parse_dt


TYPE_PRIORITY = {
    "subject": 10,
    "domain": 8,
    "task": 7,
    "artifact": 6,
    "app": 5,
    "time": 4,
    "private-signal": 3,
}

TYPE_LABELS = {
    "subject": "Subject",
    "domain": "Domain",
    "task": "Task",
    "artifact": "Artifact",
    "app": "App",
    "time": "Time",
    "private-signal": "Privacy",
}

SENSITIVE_PLACEHOLDERS = (
    "[credit-card]",
    "[email]",
    "[ip-address]",
    "[name]",
    "[phone]",
    "[redacted",
    "[secret]",
    "[ssn]",
)

PRIVATE_SIGNAL_LABELS = {
    "credit_card": "blocked card data",
    "email": "masked identity/contact",
    "ip_address": "masked network address",
    "name": "masked identity/contact",
    "phone": "masked identity/contact",
    "secret": "blocked secret/token",
    "ssn": "blocked government id",
    "url": "masked URL detail",
}

TASK_BY_DOMAIN = {
    "browser-research": "research and source review",
    "coding": "build, debug, or review code",
    "communication": "communicate and follow up",
    "data": "analyze data",
    "documents": "read or write documents",
    "planning": "plan and coordinate work",
    "system": "system state",
}

TASK_KEYWORDS = [
    ("pull request", "review code changes"),
    ("merge request", "review code changes"),
    ("issue", "track implementation work"),
    ("ticket", "track implementation work"),
    ("localhost", "test local software"),
    ("arxiv", "research and source review"),
    ("docs", "research and source review"),
    ("search", "research and source review"),
    ("calendar", "plan and coordinate work"),
    ("meeting", "plan and coordinate work"),
    ("dashboard", "inspect metrics"),
    ("metrics", "inspect metrics"),
]


def _stable_id(node_type: str, label: str) -> str:
    digest = hashlib.sha1(f"{node_type}:{label.lower()}".encode("utf-8")).hexdigest()[:12]
    return f"{node_type}:{digest}"


def _gate_mode_for_label(label: str, metadata: dict[str, Any]) -> tuple[str, str, str]:
    text = label.lower()
    findings = metadata.get("redaction_findings", {})
    if "[title capture disabled]" in text:
        return "generalized", "low", "window title capture is disabled"
    if "[redacted sensitive title]" in text:
        return "masked", "high", "sensitive window title was replaced"
    if isinstance(findings, dict) and findings:
        keys = ", ".join(sorted(str(key) for key in findings))
        return "masked", "medium", f"redaction findings: {keys}"
    if any(marker in text for marker in SENSITIVE_PLACEHOLDERS):
        return "masked", "medium", "label contains a redaction placeholder"
    return "allowed", "low", "metadata allowed by current graph depth"


def _safe_label(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _node_score(node: dict[str, Any]) -> float:
    priority = TYPE_PRIORITY.get(node["type"], 1)
    return float(node["dwell_seconds"]) + float(node["events"]) * 5.0 + priority * 120.0


def _edge_score(edge: dict[str, Any]) -> float:
    return float(edge["dwell_seconds"]) + float(edge["events"]) * 4.0


def _time_bucket(value: str) -> str:
    dt = parse_dt(value)
    return dt.strftime("%Y-%m-%d %H:00")


def _domain_task(domain: str, title: str) -> str:
    text = title.lower()
    for keyword, task in TASK_KEYWORDS:
        if keyword in text:
            return task
    return TASK_BY_DOMAIN.get(domain, "unclassified work")


def _event_findings(event: dict[str, Any]) -> dict[str, int]:
    metadata = event.get("metadata", {})
    findings = metadata.get("redaction_findings", {})
    if not isinstance(findings, dict):
        return {}

    result: dict[str, int] = {}
    for key, value in findings.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            result[str(key)] = count
    return result


def _empty_graph(
    config: dict[str, Any],
    days: int,
    *,
    source_events: int = 0,
    excluded_system_events: int = 0,
) -> dict[str, Any]:
    return {
        "status": "empty",
        "days": days,
        "capture_depth": int(config.get("context_capture_depth", 1)),
        "nodes": [],
        "edges": [],
        "stats": {
            "node_count": 0,
            "edge_count": 0,
            "events": 0,
            "source_events": source_events,
            "excluded_system_events": excluded_system_events,
            "gates": {"allowed": 0, "masked": 0, "generalized": 0, "withheld": 0},
        },
        "pipeline": _pipeline_summary(config, 0, 0),
        "privacy_gates": _privacy_gates(
            config,
            {},
            {"allowed": 0, "masked": 0, "generalized": 0, "withheld": 0},
            excluded_system_events=excluded_system_events,
        ),
        "top_relationships": [],
    }


def _pipeline_summary(config: dict[str, Any], node_count: int, edge_count: int) -> list[dict[str, Any]]:
    depth = int(config.get("context_capture_depth", 1))
    return [
        {
            "stage": "Sense",
            "state": "active",
            "output": "active-window metadata stream",
        },
        {
            "stage": "Privacy Gate",
            "state": "enforced",
            "output": f"depth {depth} policy plus PII masking",
        },
        {
            "stage": "Context Graph",
            "state": "derived",
            "output": f"{node_count} nodes and {edge_count} edges",
        },
        {
            "stage": "DTS",
            "state": "rolling",
            "output": "behavioral vector from graph-backed events",
        },
        {
            "stage": "Evidence",
            "state": "queryable",
            "output": "ranked context with gate explanations",
        },
    ]


def _privacy_gates(
    config: dict[str, Any],
    redaction_summary: dict[str, int],
    mode_counts: dict[str, int],
    *,
    excluded_system_events: int = 0,
) -> list[dict[str, Any]]:
    depth = int(config.get("context_capture_depth", 1))
    return [
        {
            "name": "Depth Policy",
            "status": "enforced",
            "decision": f"Depth {depth}: active app, title, timestamp, dwell, domain",
            "detail": "deeper browser, IDE, meeting, and document sources remain opt-in",
        },
        {
            "name": "Pre-Storage Redaction",
            "status": "enforced" if config.get("mask_pii", True) else "off",
            "decision": "mask PII, cards, secrets, names, IPs, and URL paths before graphing",
            "detail": redaction_summary or {"sensitive_text": 0},
        },
        {
            "name": "Graph Minimization",
            "status": "enforced",
            "decision": "keep typed relationships, aggregate repeated nodes, limit graph size",
            "detail": {
                **mode_counts,
                "system_state_events_excluded": excluded_system_events,
            },
        },
        {
            "name": "Sensitive Source Boundary",
            "status": "enforced",
            "decision": "no keystrokes, clipboard, screenshots, microphone, camera, passwords, or tokens",
            "detail": "blocked at collector and repeated in graph policy",
        },
    ]


class ContextGraphBuilder:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.redaction_summary: Counter[str] = Counter()

    def add_node(
        self,
        node_type: str,
        label: str,
        *,
        dwell_seconds: float,
        gate_mode: str = "allowed",
        sensitivity: str = "low",
        gate_reason: str = "allowed",
        events: int = 1,
    ) -> str:
        clean_label = _safe_label(label, f"unknown {node_type}")
        node_id = _stable_id(node_type, clean_label)
        if node_id not in self.nodes:
            self.nodes[node_id] = {
                "id": node_id,
                "type": node_type,
                "type_label": TYPE_LABELS.get(node_type, node_type.title()),
                "label": clean_label,
                "events": 0,
                "dwell_seconds": 0.0,
                "weight": 0.0,
                "gate_mode": gate_mode,
                "sensitivity": sensitivity,
                "gate_reason": gate_reason,
            }
        else:
            node = self.nodes[node_id]
            if node["gate_mode"] == "allowed" and gate_mode != "allowed":
                node["gate_mode"] = gate_mode
                node["sensitivity"] = sensitivity
                node["gate_reason"] = gate_reason

        node = self.nodes[node_id]
        node["events"] += events
        node["dwell_seconds"] = round(float(node["dwell_seconds"]) + dwell_seconds, 2)
        node["weight"] = round(_node_score(node), 2)
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        *,
        dwell_seconds: float,
        gate_mode: str = "allowed",
    ) -> None:
        if source == target:
            return
        edge_id = f"{source}->{relation}->{target}"
        if edge_id not in self.edges:
            self.edges[edge_id] = {
                "id": edge_id,
                "source": source,
                "target": target,
                "relation": relation,
                "label": relation.replace("_", " "),
                "events": 0,
                "dwell_seconds": 0.0,
                "weight": 0.0,
                "gate_mode": gate_mode,
            }
        edge = self.edges[edge_id]
        edge["events"] += 1
        edge["dwell_seconds"] = round(float(edge["dwell_seconds"]) + dwell_seconds, 2)
        edge["weight"] = round(_edge_score(edge), 2)
        if edge["gate_mode"] == "allowed" and gate_mode != "allowed":
            edge["gate_mode"] = gate_mode

    def add_event(self, event: dict[str, Any], previous: dict[str, Any] | None) -> None:
        dwell = float(event.get("dwell_seconds", 0.0))
        subject = self.add_node(
            "subject",
            "you",
            dwell_seconds=dwell,
            gate_mode="generalized",
            sensitivity="low",
            gate_reason="subject id generalized",
        )

        metadata = event.get("metadata", {})
        title = _safe_label(event.get("artifact") or event.get("title"), "untitled artifact")
        artifact_mode, artifact_sensitivity, artifact_reason = _gate_mode_for_label(title, metadata)
        app = self.add_node("app", _safe_label(event.get("app"), "unknown app"), dwell_seconds=dwell)
        domain = self.add_node("domain", _safe_label(event.get("domain"), "other"), dwell_seconds=dwell)
        artifact = self.add_node(
            "artifact",
            title,
            dwell_seconds=dwell,
            gate_mode=artifact_mode,
            sensitivity=artifact_sensitivity,
            gate_reason=artifact_reason,
        )
        task_label = _domain_task(event.get("domain", "other"), f"{event.get('title', '')} {title}")
        task = self.add_node("task", task_label, dwell_seconds=dwell)
        time_block = self.add_node("time", _time_bucket(event["ts_start"]), dwell_seconds=dwell)

        self.add_edge(subject, domain, "focused_in", dwell_seconds=dwell)
        self.add_edge(domain, app, "worked_through", dwell_seconds=dwell)
        self.add_edge(app, artifact, "opened", dwell_seconds=dwell, gate_mode=artifact_mode)
        self.add_edge(artifact, task, "suggests_task", dwell_seconds=dwell, gate_mode=artifact_mode)
        self.add_edge(time_block, domain, "observed", dwell_seconds=dwell)

        if previous:
            previous_domain = _safe_label(previous.get("domain"), "other")
            previous_artifact = _safe_label(previous.get("artifact") or previous.get("title"), "untitled artifact")
            prev_domain_node = self.add_node("domain", previous_domain, dwell_seconds=0.0, events=0)
            prev_artifact_node = self.add_node("artifact", previous_artifact, dwell_seconds=0.0, events=0)
            if prev_domain_node != domain:
                self.add_edge(prev_domain_node, domain, "transitioned_to", dwell_seconds=dwell)
            if prev_artifact_node != artifact:
                self.add_edge(prev_artifact_node, artifact, "next_context", dwell_seconds=dwell)

        for finding, count in _event_findings(event).items():
            self.redaction_summary[finding] += count
            label = PRIVATE_SIGNAL_LABELS.get(finding, f"masked {finding.replace('_', ' ')}")
            private_signal = self.add_node(
                "private-signal",
                label,
                dwell_seconds=0.0,
                gate_mode="masked",
                sensitivity="high",
                gate_reason=f"{finding} removed before graph construction",
                events=count,
            )
            self.add_edge(artifact, private_signal, "redacted_from", dwell_seconds=0.0, gate_mode="masked")

    def build(self, events: list[dict[str, Any]], *, days: int, max_nodes: int, max_edges: int) -> dict[str, Any]:
        events = filter_window(events, days)
        source_event_count = len(events)
        excluded_system_events = 0
        if not self.config.get("context_graph_include_system_events", False):
            context_events = [
                event
                for event in events
                if event.get("domain") != "system" and event.get("action") != "system"
            ]
            excluded_system_events = source_event_count - len(context_events)
            events = context_events

        if not events:
            return _empty_graph(
                self.config,
                days,
                source_events=source_event_count,
                excluded_system_events=excluded_system_events,
            )

        ordered = sorted(events, key=lambda item: item["ts_start"])
        previous = None
        for event in ordered:
            self.add_event(event, previous)
            previous = event

        nodes = sorted(self.nodes.values(), key=_node_score, reverse=True)
        subject_nodes = [node for node in nodes if node["type"] == "subject"]
        selected: dict[str, dict[str, Any]] = {}
        for node in subject_nodes + nodes:
            selected[node["id"]] = node
            if len(selected) >= max_nodes:
                break

        edges = [
            edge
            for edge in sorted(self.edges.values(), key=_edge_score, reverse=True)
            if edge["source"] in selected and edge["target"] in selected
        ][:max_edges]

        top_relationships = []
        for edge in edges[:14]:
            source = selected[edge["source"]]
            target = selected[edge["target"]]
            top_relationships.append(
                {
                    "source": source["label"],
                    "source_type": source["type"],
                    "target": target["label"],
                    "target_type": target["type"],
                    "relation": edge["label"],
                    "events": edge["events"],
                    "dwell_seconds": edge["dwell_seconds"],
                    "gate_mode": edge["gate_mode"],
                }
            )

        selected_modes = Counter(str(node.get("gate_mode", "allowed")) for node in selected.values())
        mode_counts = {key: int(selected_modes.get(key, 0)) for key in ("allowed", "masked", "generalized", "withheld")}
        if len(self.nodes) > len(selected):
            mode_counts["withheld"] += len(self.nodes) - len(selected)

        return {
            "status": "ready",
            "days": days,
            "capture_depth": int(self.config.get("context_capture_depth", 1)),
            "nodes": list(selected.values()),
            "edges": edges,
            "stats": {
                "node_count": len(selected),
                "edge_count": len(edges),
                "events": len(events),
                "source_events": source_event_count,
                "excluded_system_events": excluded_system_events,
                "gates": mode_counts,
                "redaction_summary": dict(sorted(self.redaction_summary.items())),
                "oldest_event": ordered[0]["ts_start"],
                "newest_event": ordered[-1]["ts_start"],
            },
            "pipeline": _pipeline_summary(self.config, len(selected), len(edges)),
            "privacy_gates": _privacy_gates(
                self.config,
                dict(sorted(self.redaction_summary.items())),
                mode_counts,
                excluded_system_events=excluded_system_events,
            ),
            "top_relationships": top_relationships,
        }


def build_context_graph(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    days: int = 14,
    max_nodes: int | None = None,
    max_edges: int | None = None,
) -> dict[str, Any]:
    node_limit = int(max_nodes or config.get("context_graph_max_nodes", 70))
    edge_limit = int(max_edges or config.get("context_graph_max_edges", 140))
    builder = ContextGraphBuilder(config)
    return builder.build(events, days=days, max_nodes=node_limit, max_edges=edge_limit)
