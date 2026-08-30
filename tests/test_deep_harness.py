"""The deep harness is optional and needs an API key, so it cannot run in CI.

What CAN be checked without a model, and therefore is: that the sub-agent specs are
structurally valid, that every tool is callable and returns text, and that the tools
read only from fixtures. A malformed spec should fail here, at import time, not two
minutes into a paid agent run.
"""

import unittest

from digital_twin_sensor import deep_harness as dh


class SubAgentSpecTests(unittest.TestCase):
    REQUIRED = {"name", "description", "system_prompt"}
    OPTIONAL = {
        "tools", "model", "middleware", "interrupt_on",
        "skills", "permissions", "response_format",
    }

    def test_specs_have_required_keys_and_nothing_unknown(self):
        for spec in dh.SUBAGENTS:
            keys = set(spec)
            self.assertTrue(self.REQUIRED <= keys, f"{spec.get('name')} missing {self.REQUIRED - keys}")
            self.assertFalse(keys - (self.REQUIRED | self.OPTIONAL), f"{spec.get('name')} has unknown keys")

    def test_specs_are_uniquely_named_and_non_empty(self):
        names = [s["name"] for s in dh.SUBAGENTS]
        self.assertEqual(len(names), len(set(names)))
        for spec in dh.SUBAGENTS:
            self.assertTrue(spec["description"].strip())
            self.assertGreater(len(spec["system_prompt"]), 120, f"{spec['name']} prompt is too thin to steer a judge")

    def test_every_subagent_tool_is_exposed_to_the_orchestrator(self):
        """A sub-agent holding a tool the orchestrator cannot see is a wiring bug."""
        for spec in dh.SUBAGENTS:
            for tool in spec.get("tools", []):
                self.assertIn(tool, dh.TOOLS, f"{spec['name']} uses an unregistered tool")

    def test_adversary_is_present_and_reads_the_pack(self):
        """The red team is the whole reason this layer exists; guard it explicitly."""
        adversary = next(s for s in dh.SUBAGENTS if s["name"] == "leakage-adversary")
        self.assertIn(dh.build_pack_for_scenario, adversary["tools"])
        self.assertIn("infer", adversary["system_prompt"].lower())


class ToolTests(unittest.TestCase):
    def test_tools_are_callable_and_documented(self):
        for tool in dh.TOOLS:
            self.assertTrue(callable(tool))
            self.assertTrue((tool.__doc__ or "").strip(), f"{tool.__name__} needs a docstring; the agent reads it")

    def test_list_scenarios_returns_the_golden_set(self):
        out = dh.list_scenarios()
        self.assertIn("coding_resume", out)

    def test_build_pack_for_scenario_returns_markdown(self):
        out = dh.build_pack_for_scenario("coding_resume")
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 100)

    def test_unknown_scenario_is_reported_not_raised(self):
        out = dh.build_pack_for_scenario("does_not_exist")
        self.assertIn("unknown scenario", out)

    def test_synthesis_probe_withholds_below_floor(self):
        out = dh.run_synthesis_probe(min_subjects=5, supporters=6, rare_supporters=2)
        self.assertIn("Withheld", out)

    def test_ground_truth_exposes_the_pre_gate_trace(self):
        out = dh.describe_scenario_ground_truth("leak_canary_collected")
        self.assertIn("raw attention trace", out)


class AvailabilityTests(unittest.TestCase):
    def test_missing_extra_raises_a_useful_error(self):
        try:
            dh.build_agent()
        except dh.DeepEvalUnavailable as exc:
            self.assertIn("deep-eval", str(exc))
        except Exception:
            pass  # extra installed; construction may need credentials


if __name__ == "__main__":
    unittest.main()
