"""Judgement-based evaluation of the context pipeline, using deep agents.

WHY THIS IS SEPARATE FROM harness.py
------------------------------------
`harness.py` is deterministic, dependency-free and fast. It is the CI gate, and it
stays that way: a build must not depend on a model API being reachable, or on a
non-deterministic judge, and the core sensor must remain installable with zero
runtime dependencies. That is the product.

But determinism has a ceiling. A regex canary proves a known string did not escape.
It cannot answer the questions that actually decide whether this system is any good:

  - could a person resume this work from this pack, or is it just tidy?
  - what can be *inferred* about someone from a pack that leaked no literal PII?
  - do synthesis themes describe real work, or are they token soup that reads well?
  - what is missing that should have been there?

Those are judgements. This module makes them with a planner and four adversarial
sub-agents, each with an isolated context window, over the *real* pipeline — the
same build_working_spheres → build_context_pack → synthesize_collective chain the
product runs. It evaluates the chain, not a stage.

INSTALL AND DATA BOUNDARY
-------------------------
Optional extra, developer-time only, never a runtime dependency:

    pip install -e ".[deep-eval]"          # needs Python >=3.11
    export ANTHROPIC_API_KEY=...           # or any provider deepagents supports
    digital-twin-sensor deep-harness

It runs against **synthetic fixtures from harness/scenarios.json by default**. It
will not touch the local event store unless explicitly forced, because sending real
captured attention to a model API is precisely the thing this product exists to
avoid. The force flag prints what it is about to do and requires confirmation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .config import DEFAULT_CONFIG
from .context_pack import build_context_pack, format_context_pack_markdown
from .harness import build_events, load_scenarios, run_harness
from .synthesis import subject_key, synthesize_collective
from .working_spheres import build_working_spheres

DEFAULT_MODEL = "anthropic:claude-sonnet-4-5"


class DeepEvalUnavailable(RuntimeError):
    """Raised when the optional deep-eval extra is not installed."""


def _require_deepagents():
    try:
        from deepagents import create_deep_agent  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised by the CLI path
        raise DeepEvalUnavailable(
            "deep-harness needs the optional extra:\n"
            '    pip install -e ".[deep-eval]"\n'
            "The deterministic harness (digital-twin-sensor harness) has no such "
            "requirement and remains the CI gate."
        ) from exc
    return create_deep_agent


# --------------------------------------------------------------------------
# Tools. These expose the real pipeline to the agent. Each returns a string,
# because a sub-agent reasons over text, and each is deliberately read-only:
# nothing here can write to the event store or change configuration.
# --------------------------------------------------------------------------


def _config() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_CONFIG))


def list_scenarios() -> str:
    """List the golden-set scenarios available for evaluation, with descriptions."""
    lines = []
    for scenario in load_scenarios():
        lines.append(f"- {scenario['name']}: {scenario.get('description', '')}")
    return "\n".join(lines) or "no scenarios found"


def build_pack_for_scenario(scenario_name: str) -> str:
    """Run one golden-set scenario through the real pipeline and return the context
    pack a target agent would actually receive, rendered as markdown.

    Args:
        scenario_name: name from list_scenarios, e.g. "coding_resume".
    """
    scenarios = {s["name"]: s for s in load_scenarios()}
    scenario = scenarios.get(scenario_name)
    if scenario is None:
        return f"unknown scenario {scenario_name!r}. Available: {', '.join(scenarios)}"

    config = _config()
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
    return format_context_pack_markdown(pack)


def describe_scenario_ground_truth(scenario_name: str) -> str:
    """Return what the scenario says the person was actually doing, so a judge can
    compare the pack against the truth rather than against its own guess.

    Args:
        scenario_name: name from list_scenarios.
    """
    scenarios = {s["name"]: s for s in load_scenarios()}
    scenario = scenarios.get(scenario_name)
    if scenario is None:
        return f"unknown scenario {scenario_name!r}"
    titles = [f"  - {e.get('title')} (x{e.get('repeat', 1)})" for e in scenario.get("events", [])]
    return (
        f"scenario: {scenario['name']}\n"
        f"description: {scenario.get('description','')}\n"
        f"purpose: {scenario.get('purpose')} -> target: {scenario.get('target')}\n"
        "raw attention trace before any gating:\n" + "\n".join(titles)
    )


def run_deterministic_harness() -> str:
    """Run the fast deterministic harness and return its report. Use this first:
    anything it already catches does not need judgement."""
    from .harness import format_report_markdown  # noqa: PLC0415

    return format_report_markdown(run_harness())


def run_synthesis_probe(min_subjects: int = 5, supporters: int = 6, rare_supporters: int = 2) -> str:
    """Exercise the collective synthesis layer and return its output, so its
    aggregation floor can be inspected.

    Args:
        min_subjects: the floor a theme must clear to be emitted.
        supporters: how many subjects share a common theme.
        rare_supporters: how many share a rare, potentially identifying theme.
    """
    def sphere(label: str, domain: str) -> dict[str, Any]:
        return {
            "label": label, "domain": domain, "events": 10,
            "dwell_seconds": 3600.0, "last_age_seconds": 600,
        }

    bundles = [
        {"subject_key": subject_key(f"common-{i}"),
         "activities": {"spheres": [sphere("payments gateway retry logic", "coding")]}}
        for i in range(supporters)
    ] + [
        {"subject_key": subject_key(f"rare-{i}"),
         "activities": {"spheres": [sphere("personal tax return filing", "finance")]}}
        for i in range(rare_supporters)
    ]
    from .synthesis import format_synthesis_markdown  # noqa: PLC0415

    return format_synthesis_markdown(
        synthesize_collective(bundles, min_subjects=min_subjects)
    )


TOOLS = [
    list_scenarios,
    describe_scenario_ground_truth,
    build_pack_for_scenario,
    run_deterministic_harness,
    run_synthesis_probe,
]


# --------------------------------------------------------------------------
# Sub-agents. Each gets an isolated context window, which is the point: the
# adversary must not be softened by having read the relevance judge's praise.
# --------------------------------------------------------------------------

RESUMABILITY_JUDGE = {
    "name": "resumability-judge",
    "description": (
        "Judges whether a context pack would actually let someone resume interrupted "
        "work. Use for every scenario that is expected to produce a usable pack."
    ),
    "system_prompt": (
        "You judge whether a context pack is sufficient to RESUME work, not whether it "
        "is well formatted.\n\n"
        "Call describe_scenario_ground_truth first, then build_pack_for_scenario. "
        "Compare them.\n\n"
        "Ask: if I were handed only this pack and told to continue, what would I do "
        "next? What would I have to guess? What would I get wrong?\n\n"
        "A tidy pack that omits the one artifact the person kept returning to is a "
        "FAIL, however clean it looks. A blunt pack that names the right thing and "
        "its state is a PASS. Reward specificity, punish summary that reads well and "
        "says nothing.\n\n"
        "Report: verdict (pass/fail), what is missing, and the single change that "
        "would most improve resumability."
    ),
    "tools": [describe_scenario_ground_truth, build_pack_for_scenario],
}

LEAKAGE_ADVERSARY = {
    "name": "leakage-adversary",
    "description": (
        "Red team. Tries to re-identify or infer sensitive facts about the subject "
        "from a gated pack. Use on every scenario, especially ones that pass the "
        "deterministic canaries."
    ),
    "system_prompt": (
        "You are an adversary with access only to an exported context pack. Your goal "
        "is to learn things about the person that the gate intended to withhold.\n\n"
        "The deterministic harness already checks that literal strings did not escape. "
        "You look for what it cannot: INFERENCE. From artifact names, domains, timing "
        "and rhythm, try to determine the employer, the client, the project, the "
        "person's role and seniority, their working hours, and anything about their "
        "personal life.\n\n"
        "State each inference and the exact evidence in the pack that supports it. Rate "
        "confidence. Do not speculate without evidence — a false alarm wastes the "
        "reviewer's attention and makes real findings easier to dismiss.\n\n"
        "Finish with the single highest-risk inference and the specific field that "
        "should have been masked to prevent it."
    ),
    "tools": [build_pack_for_scenario, describe_scenario_ground_truth],
}

SYNTHESIS_CRITIC = {
    "name": "synthesis-critic",
    "description": (
        "Evaluates the collective synthesis layer: are themes coherent, and does the "
        "aggregation floor actually protect small groups?"
    ),
    "system_prompt": (
        "You evaluate cross-subject synthesis output.\n\n"
        "Two questions. First: do the emitted themes describe recognisable WORK, or "
        "are they token soup that happens to read like English? A theme a manager "
        "could not act on is a failure of the layer, not a presentation problem.\n\n"
        "Second: probe the floor. Call run_synthesis_probe with different "
        "min_subjects and rare_supporters values. Confirm a rare theme stays withheld "
        "as supporters approach the floor, and that the withheld COUNT is still "
        "reported — silent suppression is its own failure, because an operator who "
        "cannot see that suppression happened will read a thin answer as a complete one.\n\n"
        "Report: theme coherence verdict, floor behaviour, and any way you found to "
        "get a small group's theme emitted."
    ),
    "tools": [run_synthesis_probe],
}

GAP_ANALYST = {
    "name": "gap-analyst",
    "description": (
        "Looks for the scenario the golden set does not contain — the untested case "
        "most likely to break in production."
    ),
    "system_prompt": (
        "You review the golden set for what it does NOT test.\n\n"
        "Call list_scenarios and run_deterministic_harness. The suite passing tells "
        "you the suite is weak or the system is good, and you must work out which.\n\n"
        "Propose concrete missing scenarios in the same JSON shape, prioritised by "
        "how likely each is to break in real use. Favour cases where the system would "
        "fail SILENTLY — wrong-but-plausible context is far more dangerous than an "
        "empty pack, because nobody investigates a confident answer.\n\n"
        "Report the three highest-value missing scenarios, each with the failure it "
        "would catch."
    ),
    "tools": [list_scenarios, run_deterministic_harness, build_pack_for_scenario],
}

SUBAGENTS = [RESUMABILITY_JUDGE, LEAKAGE_ADVERSARY, SYNTHESIS_CRITIC, GAP_ANALYST]

ORCHESTRATOR_PROMPT = """You evaluate a privacy-gated context pipeline end to end.

The system captures attention on one machine, redacts before storage, clusters work
into spheres, gates exports through a Memory Admission Gate, and synthesises across
subjects behind an aggregation floor. Your job is to decide whether the context it
produces is useful enough to matter and safe enough to ship.

Work in this order:

1. Call run_deterministic_harness. Whatever it already catches needs no judgement
   from you; note it and move on.
2. Call list_scenarios to see the golden set.
3. For each scenario expected to produce a usable pack, delegate to
   resumability-judge.
4. For EVERY scenario, delegate to leakage-adversary — including the ones that
   passed. Passing the literal-string canaries is exactly when inference risk
   hides.
5. Delegate once to synthesis-critic and once to gap-analyst.
6. Write the report.

Be concrete and be hard to please. "Looks good" is not a finding. Every claim needs
the evidence that supports it. If the system is genuinely fine on a dimension, say so
plainly and briefly rather than inventing a concern to seem rigorous — a padded report
trains the reader to skim.

Rank findings by what would hurt most in a real deployment, not by how many you found.
"""


@dataclass
class DeepEvalConfig:
    model: str = DEFAULT_MODEL
    scenarios_only: bool = True


def build_agent(model: str = DEFAULT_MODEL):
    """Construct the deep agent. Raises DeepEvalUnavailable if the extra is missing."""
    create_deep_agent = _require_deepagents()
    return create_deep_agent(
        model=model,
        tools=TOOLS,
        system_prompt=ORCHESTRATOR_PROMPT,
        subagents=SUBAGENTS,
    )


def run_deep_harness(model: str = DEFAULT_MODEL, prompt: str | None = None) -> str:
    """Run the full judgement-based evaluation and return the agent's report."""
    agent = build_agent(model)
    task = prompt or (
        "Evaluate the context pipeline end to end using the golden set. "
        "Produce a prioritised report with evidence for every claim."
    )
    result = agent.invoke({"messages": [{"role": "user", "content": task}]})
    messages = result.get("messages", [])
    if not messages:
        return "the agent returned no messages"
    final = messages[-1]
    return getattr(final, "content", None) or str(final)
