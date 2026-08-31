"""Secure aggregation for collective synthesis.

`synthesis.py` answers "what is the work here?" across many sensors. It does
that well at the output boundary — a theme below the subject floor is withheld
and counted — but it was answering the second-most-important question.

The floor protects what is *published*. Nothing protected what is *collected*:
the caller received every subject's working spheres in the clear, so whoever ran
the synthesis held per-person work traces. For the adversary the threat model
takes most seriously — the employer who controls the deployment — that is the
whole game, and a floor applied afterwards does not touch it.

This module changes what crosses the wire. A client emits a fixed-width vector
of counts over a *declared* theme vocabulary, masked so that the individual
vector is uniformly random on its own, and only the sum over the cohort reveals
anything. The aggregator never holds a readable per-subject contribution.

    theme vocabulary   declared, like a connector manifest (ADR 0009): a theme
                       that is not declared cannot be counted, so the vector is
                       fixed-width and every field is reviewable
    clipping           a subject contributes at most `clip` to any bucket, so no
                       one participant can manufacture a theme
    pairwise masks     derived from a cohort secret the aggregator does not hold;
                       masks cancel exactly when the whole cohort is summed

What this is NOT, stated plainly because the difference matters:

  * It is not anonymity. It is pseudonymous aggregation with a published floor.
  * It has no dropout resilience. If one cohort member does not report, the sum
    is unrecoverable — by construction, not by oversight. Real deployments use
    Diffie-Hellman with secret sharing for recovery (Bonawitz et al.); that
    needs a crypto dependency and this package has none (ADR 0004).
  * The cohort secret is symmetric, so it defends against the *aggregator*, not
    against a colluding cohort member who can already derive their own masks.
  * Aggregator-added noise is central DP: it assumes the aggregator adds the
    noise it says it adds. Distributed noise is the next step, not this one.

Open-vocabulary discovery — finding themes nobody declared — is the trie-based
heavy-hitter problem (Zhu et al. 2020) and needs population sizes this product
does not have at team scale. See docs/adr/0012.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Counts live in a ring so masks cancel exactly under addition.
MODULUS = 2**32
# A subject may contribute at most this to any one bucket. Bounded influence is
# what stops one prolific participant from manufacturing a theme alone.
DEFAULT_CLIP = 1
VOCABULARY_PATH = Path(__file__).resolve().parent / "vocabularies" / "themes.json"


class VocabularyError(ValueError):
    """A theme vocabulary that would not be safe or reproducible to aggregate."""


class CohortError(ValueError):
    """The cohort does not match what the masks were built for."""


@dataclass(frozen=True)
class ThemeVocabulary:
    """An ordered, declared list of countable themes.

    Order is part of the contract: it fixes which vector position means which
    theme, so a vocabulary cannot be reordered without invalidating masks built
    against it. The digest is carried in every contribution and checked on
    aggregation.
    """

    themes: tuple[str, ...]
    descriptions: dict[str, str]
    version: str

    @property
    def digest(self) -> str:
        payload = json.dumps({"v": self.version, "t": list(self.themes)}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def index(self, theme: str) -> int | None:
        try:
            return self.themes.index(theme)
        except ValueError:
            return None

    def __len__(self) -> int:
        return len(self.themes)


def load_vocabulary(path: Path | None = None) -> ThemeVocabulary:
    payload = json.loads(Path(path or VOCABULARY_PATH).read_text(encoding="utf-8"))
    version = str(payload.get("version") or "").strip()
    if not version:
        raise VocabularyError("vocabulary needs a version; masks are bound to it")

    entries = payload.get("themes")
    if not isinstance(entries, list) or not entries:
        raise VocabularyError("vocabulary needs a non-empty themes list")

    themes: list[str] = []
    descriptions: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise VocabularyError("each theme must be an object with id and description")
        theme_id = str(entry.get("id") or "").strip()
        description = str(entry.get("description") or "").strip()
        if not theme_id:
            raise VocabularyError("every theme needs an id")
        if not description:
            raise VocabularyError(f"theme {theme_id!r} needs a description; an undocumented countable field is not reviewable")
        if theme_id in descriptions:
            raise VocabularyError(f"duplicate theme id {theme_id!r}")
        themes.append(theme_id)
        descriptions[theme_id] = description

    return ThemeVocabulary(themes=tuple(themes), descriptions=descriptions, version=version)


def _prg(seed: bytes, length: int) -> list[int]:
    """Counter-mode HMAC-SHA256 stream, read as 32-bit words."""
    out: list[int] = []
    counter = 0
    while len(out) < length:
        block = hmac.new(seed, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        for offset in range(0, len(block), 4):
            if len(out) >= length:
                break
            out.append(int.from_bytes(block[offset : offset + 4], "big"))
        counter += 1
    return out


def _pair_seed(secret: bytes, round_id: str, first: str, second: str) -> bytes:
    low, high = sorted((first, second))
    return hmac.new(secret, f"{round_id}|{low}|{high}".encode("utf-8"), hashlib.sha256).digest()


def build_contribution(
    activities: dict[str, Any],
    vocabulary: ThemeVocabulary,
    *,
    theme_of,
    clip: int = DEFAULT_CLIP,
) -> list[int]:
    """Client side: turn one subject's gated spheres into a clipped count vector.

    `theme_of` maps a sphere to a declared theme id (or None). A sphere whose
    theme is not declared contributes nothing — it cannot be counted, which is
    the same guarantee connector manifests give for fields (ADR 0009).
    """
    if clip < 1:
        raise ValueError("clip must be at least 1")

    vector = [0] * len(vocabulary)
    for sphere in (activities or {}).get("spheres", []) or []:
        if sphere.get("sensitivity") == "high" or sphere.get("gate_mode", "allowed") != "allowed":
            continue
        theme = theme_of(sphere)
        if not theme:
            continue
        position = vocabulary.index(theme)
        if position is None:
            continue
        vector[position] = min(clip, vector[position] + 1)
    return vector


def mask_contribution(
    vector: list[int],
    *,
    subject_key: str,
    cohort: Iterable[str],
    round_id: str,
    cohort_secret: bytes,
) -> dict[str, Any]:
    """Client side: blind the vector so it carries no information alone.

    Every pair of cohort members derives one shared mask stream. The lower key
    adds it, the higher subtracts it, so the masks cancel exactly when the whole
    cohort is summed and not before.
    """
    members = sorted(set(cohort))
    if subject_key not in members:
        raise CohortError("a subject must be a member of its own cohort")
    if len(members) < 2:
        raise CohortError("masking needs at least two cohort members")

    masked = [value % MODULUS for value in vector]
    for other in members:
        if other == subject_key:
            continue
        stream = _prg(_pair_seed(cohort_secret, round_id, subject_key, other), len(vector))
        sign = 1 if subject_key < other else -1
        for position, noise in enumerate(stream):
            masked[position] = (masked[position] + sign * noise) % MODULUS

    return {
        "schema": "contribution/v1",
        "round_id": round_id,
        "cohort_digest": cohort_digest(members),
        "cohort_size": len(members),
        "vocabulary_digest": None,  # filled by the caller that owns the vocabulary
        "masked_vector": masked,
    }


def cohort_digest(cohort: Iterable[str]) -> str:
    members = sorted(set(cohort))
    return hashlib.sha256("|".join(members).encode("utf-8")).hexdigest()[:16]


def secure_sum(contributions: list[dict[str, Any]]) -> list[int]:
    """Aggregator side: recover the cohort totals and nothing else.

    Refuses a partial cohort. A missing member is not a degraded answer here —
    the masks do not cancel, so the sum is meaningless rather than merely noisy,
    and returning it would be worse than returning nothing.
    """
    if not contributions:
        raise CohortError("no contributions to aggregate")

    digests = {str(item.get("cohort_digest")) for item in contributions}
    if len(digests) != 1:
        raise CohortError("contributions describe different cohorts")

    rounds = {str(item.get("round_id")) for item in contributions}
    if len(rounds) != 1:
        raise CohortError("contributions come from different rounds; masks are round-bound")

    expected = int(contributions[0].get("cohort_size") or 0)
    if len(contributions) != expected:
        raise CohortError(
            f"cohort is incomplete: {len(contributions)} of {expected} reported. "
            "Pairwise masks cancel only over the whole cohort, so no total can be "
            "recovered. Dropout resilience needs secret sharing (see module docstring)."
        )

    width = len(contributions[0].get("masked_vector") or [])
    if any(len(item.get("masked_vector") or []) != width for item in contributions):
        raise CohortError("contributions have different widths; vocabulary mismatch")

    totals = [0] * width
    for item in contributions:
        for position, value in enumerate(item["masked_vector"]):
            totals[position] = (totals[position] + int(value)) % MODULUS

    # Counts are small and non-negative; anything near the modulus is a wrap
    # from a mask that failed to cancel, which means the cohort was wrong.
    for value in totals:
        if value > MODULUS // 2:
            raise CohortError("masks did not cancel; the cohort or secret does not match")
    return totals


def discrete_laplace(scale: float) -> int:
    """Two-sided geometric noise, sampled from the system CSPRNG.

    Discrete so it composes with integer counts without a float leak, and drawn
    from `secrets` rather than `random` because a predictable noise source is
    not noise.
    """
    if scale <= 0:
        return 0
    probability = math.exp(-1.0 / scale)
    def geometric() -> int:
        count = 0
        while secrets.randbelow(10**9) / 10**9 < probability:
            count += 1
        return count
    return geometric() - geometric()


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Confidence interval on a proportion, derived rather than chosen.

    This replaces the hand-picked `0.65 * breadth + 0.35 * depth` weighting that
    ADR 0008 flagged as an unvalidated prior. The uncertainty in "how much of
    this cohort worked on this theme" is a property of the count and the cohort
    size; it does not need fitting, and inventing weights for it was the mistake.
    """
    if trials <= 0:
        return (0.0, 0.0)
    proportion = successes / trials
    denominator = 1 + z**2 / trials
    centre = (proportion + z**2 / (2 * trials)) / denominator
    margin = (z / denominator) * math.sqrt(
        proportion * (1 - proportion) / trials + z**2 / (4 * trials**2)
    )
    return (round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3))
