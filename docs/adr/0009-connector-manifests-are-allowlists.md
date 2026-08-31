# 0009 — Connector manifests are allowlists, not parsers

**Status:** Accepted

## Context

Structured connectors turn raw surfaces (window titles, browser tabs,
accessibility trees, OCR) into named fields. Written as parsers, each new
connector is a new opportunity to store something nobody agreed to store — the
classic path by which a capture tool grows past its consent.

## Decision

A manifest is a declarative allowlist. A field that is not declared cannot be
stored, whatever a parser extracts. Every field carries a description, a store
mode (`redacted`, `token`, `count`, `domain`), a permitted source list and an
explicit denied list. Manifests are validated hard at load: unknown source,
missing description, token-without-allowlist, pattern without a `(?P<value>...)`
group, undeclared graph field and duplicate ids are all rejected outright.

Sources are consulted cheapest-first, so an expensive, invasive source is
provably never read when a cheaper one answers.

## Consequences

Adding a connector is slower and its blast radius is bounded by a file a reviewer
can read. Provenance — which source answered, at what confidence — travels with
each field into the context graph and the dashboard.

## Enforced by

`tests/test_connectors.py` (30 tests, including dashboard contract and graph
normalisation), plus the `sources_not_needed` assertion proving OCR goes
unconsulted when accessibility answers.

## What would reverse this

Nothing. A connector that needs to be a parser is a connector that needs a
manifest change and a reviewer.
