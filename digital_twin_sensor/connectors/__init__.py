"""Structured app connectors: declarative, depth-aware, allowlist-enforced."""

from .manifest import Manifest, ManifestError, load_manifests, parse_manifest
from .registry import (
    apply_connector,
    connector_for_app,
    registry,
    registry_summary,
    structured_detail,
)

__all__ = [
    "Manifest",
    "ManifestError",
    "load_manifests",
    "parse_manifest",
    "apply_connector",
    "connector_for_app",
    "registry",
    "registry_summary",
    "structured_detail",
]
