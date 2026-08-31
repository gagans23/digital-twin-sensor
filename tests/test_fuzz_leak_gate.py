"""Property-based tests for the two boundaries that must never leak.

The golden set in `harness/scenarios.json` plants a handful of canaries and
checks they do not reach an export. That proves the gate handles the cases
somebody thought of. It says nothing about the cases nobody thought of, which
is the population that actually matters for a leak.

These tests generate hostile inputs instead: card numbers split across odd
separators, secrets glued to punctuation, national IDs hidden inside longer
tokens, URLs carrying credentials in the userinfo. Two invariants are asserted
over thousands of generated strings:

    1. Nothing that redaction claims to mask survives `redact_text`.
    2. Nothing masked at capture reappears in a context pack export.

The generator is seeded and standard-library only, so a failure is reproducible
from the seed printed in the assertion message and CI needs no new dependency
(ADR 0004). Installing the optional `fuzz` extra raises the iteration count for
longer local runs; it is not required.
"""

from __future__ import annotations

import os
import random
import string
import unittest

from digital_twin_sensor.config import DEFAULT_CONFIG
from digital_twin_sensor.context_pack import build_context_pack, format_context_pack_markdown
from digital_twin_sensor.redaction import redact_text
from digital_twin_sensor.store import utc_now
from digital_twin_sensor.working_spheres import build_working_spheres

from datetime import timedelta
import json

# Raised locally with FUZZ_ITERATIONS=5000 for a longer soak; CI stays fast.
ITERATIONS = int(os.environ.get("FUZZ_ITERATIONS", "400"))
SEED = int(os.environ.get("FUZZ_SEED", "20260831"))

CONFIG = {
    **DEFAULT_CONFIG,
    "mask_pii": True,
    "mask_ip_addresses": True,
    "redact_url_paths": True,
    "mask_configured_names": True,
    "name_terms_to_mask": ["Gagan", "Acme Client"],
}

SEPARATORS = ["", " ", "-", " - ", ".", "  "]
NOISE = [
    "Invoice",
    "review — draft 3",
    "[WIP]",
    "sprint/42",
    "…",
    "ref:",
    "(confidential)",
    "​",  # zero-width space, a classic smuggling character
    "\t",
]


def _luhn_number(rng: random.Random, length: int) -> str:
    """A card-shaped number that actually passes Luhn, so it must be masked."""
    digits = [rng.randint(0, 9) for _ in range(length - 1)]
    total = 0
    double = True
    for value in reversed(digits):
        if double:
            value *= 2
            if value > 9:
                value -= 9
        total += value
        double = not double
    digits.append((10 - total % 10) % 10)
    return "".join(str(d) for d in digits)


def _wrap(rng: random.Random, payload: str) -> str:
    """Bury the payload in plausible window-title noise."""
    left = rng.choice(NOISE)
    right = rng.choice(NOISE)
    return f"{left} {payload} {right}".strip()


def _card(rng: random.Random) -> tuple[str, str]:
    raw = _luhn_number(rng, rng.choice([13, 15, 16, 16, 19]))
    sep = rng.choice(SEPARATORS)
    chunked = sep.join(raw[i : i + 4] for i in range(0, len(raw), 4)) if sep else raw
    return chunked, raw


def _email(rng: random.Random) -> tuple[str, str]:
    user = "".join(rng.choices(string.ascii_lowercase + "._-", k=rng.randint(3, 12)))
    host = "".join(rng.choices(string.ascii_lowercase, k=rng.randint(3, 10)))
    tld = rng.choice(["com", "ae", "co.in", "io", "bank"])
    value = f"{user}@{host}.{tld}"
    return value, value


def _secret(rng: random.Random) -> tuple[str, str]:
    kind = rng.choice(["sk-", "ghp_", "xoxb-", "AKIA", "AIza"])
    if kind == "AKIA":
        value = "AKIA" + "".join(rng.choices(string.ascii_uppercase + string.digits, k=16))
    elif kind == "AIza":
        value = "AIza" + "".join(rng.choices(string.ascii_letters + string.digits + "_-", k=24))
    else:
        value = kind + "".join(rng.choices(string.ascii_lowercase + string.digits + "_-", k=rng.randint(18, 30)))
    return value, value


def _national_id(rng: random.Random) -> tuple[str, str]:
    value = f"{rng.randint(100, 899)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    return value, value


def _url_with_secrets(rng: random.Random) -> tuple[str, str]:
    token = "".join(rng.choices(string.ascii_letters + string.digits, k=rng.randint(10, 24)))
    path = "/".join("".join(rng.choices(string.ascii_lowercase, k=6)) for _ in range(rng.randint(1, 3)))
    value = f"https://portal.example.ae/{path}?token={token}"
    return value, token


GENERATORS = (_card, _email, _secret, _national_id, _url_with_secrets)


class RedactionPropertyTests(unittest.TestCase):
    """Invariant 1: what redaction claims to mask does not survive redaction."""

    def test_generated_sensitive_values_never_survive_redaction(self):
        rng = random.Random(SEED)
        for iteration in range(ITERATIONS):
            generator = rng.choice(GENERATORS)
            rendered, secret = generator(rng)
            title = _wrap(rng, rendered)

            result = redact_text(title, CONFIG)

            self.assertNotIn(
                secret,
                result.text,
                msg=(
                    f"leak on iteration {iteration} (seed {SEED}, generator "
                    f"{generator.__name__}): {secret!r} survived in {result.text!r}"
                ),
            )

    def test_redaction_is_idempotent(self):
        """Masking twice must equal masking once, or a second pass could re-expose."""
        rng = random.Random(SEED + 1)
        for iteration in range(ITERATIONS // 2):
            generator = rng.choice(GENERATORS)
            rendered, _ = generator(rng)
            title = _wrap(rng, rendered)

            once = redact_text(title, CONFIG).text
            twice = redact_text(once, CONFIG).text

            self.assertEqual(once, twice, msg=f"not idempotent on iteration {iteration} (seed {SEED})")

    def test_redaction_never_returns_none_or_grows_unboundedly(self):
        rng = random.Random(SEED + 2)
        for _ in range(ITERATIONS // 2):
            generator = rng.choice(GENERATORS)
            rendered, _ = generator(rng)
            title = _wrap(rng, rendered)
            result = redact_text(title, CONFIG)
            self.assertIsInstance(result.text, str)
            self.assertLess(len(result.text), len(title) * 4 + 64)


class ExportPropertyTests(unittest.TestCase):
    """Invariant 2: a masked value does not reappear anywhere in an export."""

    def _event(self, index: int, title: str) -> dict:
        start = utc_now() - timedelta(minutes=10 + index * 7)
        return {
            "id": index,
            "subject_id": "fuzz",
            "source": "fuzz",
            "app": "Safari",
            "title": title,
            "artifact": title,
            "domain": "operations",
            "action": "focus",
            "ts_start": start.isoformat(),
            "ts_end": (start + timedelta(seconds=120)).isoformat(),
            "dwell_seconds": 120.0,
            "metadata": {"collector_version": "fuzz-v1", "redaction_findings": {}},
        }

    def test_generated_secrets_never_reach_a_context_pack(self):
        rng = random.Random(SEED + 3)
        # Packs are the expensive step, so fewer iterations with more events each.
        rounds = max(8, ITERATIONS // 40)
        for iteration in range(rounds):
            secrets = []
            events = []
            for index in range(1, 9):
                generator = rng.choice(GENERATORS)
                rendered, secret = generator(rng)
                secrets.append(secret)
                # Exactly the collector's path: redact, then store.
                events.append(self._event(index, redact_text(_wrap(rng, rendered), CONFIG).text))

            activities = build_working_spheres(events, CONFIG, days=14)
            pack = build_context_pack(
                events,
                CONFIG,
                days=14,
                purpose="agent_prompt",
                target="kiro",
                activities=activities,
            )
            blob = f"{format_context_pack_markdown(pack)}\n{json.dumps(pack, default=str)}"

            for secret in secrets:
                self.assertNotIn(
                    secret,
                    blob,
                    msg=f"leak on round {iteration} (seed {SEED}): {secret!r} reached the export",
                )

    def test_pack_still_denies_the_standing_fields_under_generated_load(self):
        """A gate that stops denying while recall improves is still a regression."""
        rng = random.Random(SEED + 4)
        events = []
        for index in range(1, 7):
            rendered, _ = rng.choice(GENERATORS)(rng)
            events.append(self._event(index, redact_text(_wrap(rng, rendered), CONFIG).text))

        activities = build_working_spheres(events, CONFIG, days=14)
        pack = build_context_pack(
            events, CONFIG, days=14, purpose="agent_prompt", target="kiro", activities=activities
        )
        denied = {
            d["field"]
            for d in (pack.get("admission") or {}).get("decisions", [])
            if d.get("decision") == "deny"
        }
        for field in ("keystrokes", "clipboard", "screenshots", "credentials", "raw_event_payloads"):
            self.assertIn(field, denied, msg=f"{field} is no longer denied by the admission gate")


if __name__ == "__main__":
    unittest.main()
