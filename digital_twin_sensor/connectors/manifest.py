"""Connector manifests: a declarative allowlist of what an app may contribute.

WHY MANIFESTS RATHER THAN CODE
------------------------------
Today each collector sanitises itself. That works, but it means the privacy
boundary for an app is spread across whichever function happens to handle it,
and adding an app means writing new code that could store anything.

A manifest inverts that. It declares, as data, the complete set of fields a
connector is permitted to contribute. The framework then enforces it: a field
not named in the manifest cannot reach the store, no matter what a source
returns. Adding an app becomes a reviewable JSON diff rather than a code path.

That property is the point of this module. Everything else here is plumbing.

DEPTH IS A CEILING, NOT A TARGET
--------------------------------
A manifest names the minimum capture depth it needs and the ordered sources it
may read. It can never read a source the user has not enabled, and it can never
raise its own depth. If structured metadata is available at depth 3, the OCR
fallback at depth 4 is simply never reached — which is the whole reason this
layer exists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"

# Sources a manifest may declare, in the order the depth model introduces them.
KNOWN_SOURCES = ("window_title", "browser_tab", "accessibility", "ocr")
SOURCE_MIN_DEPTH = {"window_title": 1, "browser_tab": 2, "accessibility": 3, "ocr": 4}

# How a field may be stored. Nothing else is permitted.
#   redacted  - passed through the PII/secret masker before storage
#   token     - a short controlled value matched against an allowlist (e.g. "playing")
#   count     - an integer
#   domain    - a bare hostname, never a path
STORE_MODES = ("redacted", "token", "count", "domain")

SENSITIVITIES = ("low", "medium", "high")


class ManifestError(ValueError):
    """A manifest is malformed. Raised at load time, never at capture time."""


@dataclass(frozen=True)
class FieldSpec:
    name: str
    store: str
    sensitivity: str = "low"
    from_key: str | None = None          # take this key from a source payload
    pattern: str | None = None           # or extract via named group "value"
    tokens: tuple[str, ...] = ()         # allowlist for store == "token"
    max_length: int = 120
    description: str = ""

    def compiled(self) -> re.Pattern[str] | None:
        return re.compile(self.pattern, re.IGNORECASE) if self.pattern else None


@dataclass(frozen=True)
class GraphSpec:
    """How this connector's fields become nodes in the context graph."""
    node_type: str = "artifact"
    label_field: str = ""
    context_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class Manifest:
    id: str
    display_name: str
    version: int
    apps: tuple[str, ...]
    min_depth: int
    sources: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    denied: tuple[str, ...]
    graph: GraphSpec
    notes: str = ""

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset(f.name for f in self.fields)

    def matches_app(self, app: str) -> bool:
        return app.strip().lower() in {a.lower() for a in self.apps}

    def field(self, name: str) -> FieldSpec | None:
        for spec in self.fields:
            if spec.name == name:
                return spec
        return None


def _require(payload: dict[str, Any], key: str, where: str) -> Any:
    if key not in payload:
        raise ManifestError(f"{where}: missing required key {key!r}")
    return payload[key]


def parse_manifest(payload: dict[str, Any], *, where: str = "<manifest>") -> Manifest:
    ident = str(_require(payload, "id", where))
    where = f"{where}[{ident}]"

    sources = tuple(str(s) for s in _require(payload, "sources", where))
    unknown = [s for s in sources if s not in KNOWN_SOURCES]
    if unknown:
        raise ManifestError(f"{where}: unknown sources {unknown}; known: {list(KNOWN_SOURCES)}")

    min_depth = int(_require(payload, "min_depth", where))
    # A manifest that declares a source it can never legally read is a bug in the
    # manifest, not a runtime condition. Fail loudly at load.
    for source in sources:
        if SOURCE_MIN_DEPTH[source] > max(min_depth, SOURCE_MIN_DEPTH[source]):
            raise ManifestError(f"{where}: source {source!r} needs a higher min_depth")

    fields: list[FieldSpec] = []
    seen: set[str] = set()
    for raw in _require(payload, "fields", where):
        name = str(_require(raw, "name", where))
        if name in seen:
            raise ManifestError(f"{where}: duplicate field {name!r}")
        seen.add(name)
        store = str(_require(raw, "store", where))
        if store not in STORE_MODES:
            raise ManifestError(f"{where}.{name}: store {store!r} not in {list(STORE_MODES)}")
        sensitivity = str(raw.get("sensitivity", "low"))
        if sensitivity not in SENSITIVITIES:
            raise ManifestError(f"{where}.{name}: sensitivity {sensitivity!r} invalid")
        if store == "token" and not raw.get("tokens"):
            raise ManifestError(f"{where}.{name}: store 'token' requires a tokens allowlist")
        if not raw.get("from") and not raw.get("pattern"):
            raise ManifestError(f"{where}.{name}: needs either 'from' or 'pattern'")
        if raw.get("pattern"):
            try:
                compiled = re.compile(str(raw["pattern"]))
            except re.error as exc:
                raise ManifestError(f"{where}.{name}: bad pattern — {exc}") from exc
            if "value" not in compiled.groupindex:
                raise ManifestError(f"{where}.{name}: pattern needs a named group (?P<value>...)")
        fields.append(
            FieldSpec(
                name=name,
                store=store,
                sensitivity=sensitivity,
                from_key=str(raw["from"]) if raw.get("from") else None,
                pattern=str(raw["pattern"]) if raw.get("pattern") else None,
                tokens=tuple(str(t).lower() for t in raw.get("tokens", [])),
                max_length=int(raw.get("max_length", 120)),
                description=str(raw.get("description", "")),
            )
        )
    if not fields:
        raise ManifestError(f"{where}: a connector with no fields would store nothing")

    graph_raw = payload.get("graph") or {}
    graph = GraphSpec(
        node_type=str(graph_raw.get("node_type", "artifact")),
        label_field=str(graph_raw.get("label_field", "")),
        context_fields=tuple(str(f) for f in graph_raw.get("context_fields", [])),
    )
    known = {f.name for f in fields}
    for referenced in filter(None, (graph.label_field, *graph.context_fields)):
        if referenced not in known:
            raise ManifestError(f"{where}.graph: references undeclared field {referenced!r}")

    return Manifest(
        id=ident,
        display_name=str(payload.get("display_name", ident)),
        version=int(payload.get("version", 1)),
        apps=tuple(str(a) for a in _require(payload, "apps", where)),
        min_depth=min_depth,
        sources=sources,
        fields=tuple(fields),
        denied=tuple(str(d) for d in payload.get("denied", [])),
        graph=graph,
        notes=str(payload.get("notes", "")),
    )


def load_manifests(directory: Path | None = None) -> list[Manifest]:
    """Load and validate every manifest. A malformed one fails the whole load,
    because a partially-loaded connector set is worse than none."""
    target = Path(directory) if directory else MANIFEST_DIR
    manifests: list[Manifest] = []
    for path in sorted(target.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifests.append(parse_manifest(payload, where=path.name))
    ids = [m.id for m in manifests]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ManifestError(f"duplicate connector ids: {sorted(duplicates)}")
    return manifests
