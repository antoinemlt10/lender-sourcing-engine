"""Enrichment: turn a SeedCompany into a fully-annotated Account.

PublicWebEnricher uses two Claude calls per company:
  1. extract_signals (with web search) -> strict JSON with the 7 scoring
     factors, evidence, snapshot and role-level personas.
  2. poc_angle (no web search) -> a short tailored POC angle written from
     the extracted signals.

The Enricher Protocol keeps this pluggable: a Clay/Apollo-backed enricher
can drop in later without touching the pipeline.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from lender_engine.config import ICPConfig
from lender_engine.llm import ClaudeClient
from lender_engine.models import (
    Account,
    Evidence,
    Factor,
    OperationalScores,
    Persona,
    SeedCompany,
    StructuralScores,
)


class EnrichmentError(Exception):
    """The model's output could not be turned into an Account."""


@runtime_checkable
class Enricher(Protocol):
    """Anything that can enrich a seed company into an Account.

    Implementations raise EnrichmentError on unrecoverable failure.
    """

    def enrich(self, seed: SeedCompany, icp: ICPConfig) -> Account: ...


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse the first JSON object out of model output, tolerating code fences.

    Strategy: find the first '{' (which skips any ```json fence or preamble)
    and decode exactly one complete object from there with raw_decode, so any
    trailing prose or stray braces after the object are ignored.
    """
    start = text.find("{")
    if start == -1:
        raise EnrichmentError(
            f"No JSON object found in model output (first 200 chars): {text[:200]!r}"
        )
    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise EnrichmentError(f"Model output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EnrichmentError(f"Expected a JSON object, got {type(data).__name__}")
    return data


def _parse_evidence(raw: Any) -> list[Evidence]:
    items: list[Evidence] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        confidence = entry.get("confidence", "inferred")
        if confidence not in ("sourced", "inferred"):
            confidence = "inferred"
        items.append(
            Evidence(
                claim=str(entry.get("claim", "")),
                source_url=str(entry.get("source_url", "")),
                confidence=confidence,
            )
        )
    return items


def _parse_factor(name: str, raw: Any) -> Factor:
    if not isinstance(raw, dict):
        raise EnrichmentError(f"Factor '{name}' is missing or not an object")
    try:
        value = float(raw["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EnrichmentError(f"Factor '{name}' has no numeric 'value'") from exc
    value = min(1.0, max(0.0, value))  # clamp: factors are 0-1 by contract
    return Factor(
        value=value,
        rationale=str(raw.get("rationale", "")),
        evidence=_parse_evidence(raw.get("evidence")),
    )


def _parse_persona(name: str, raw: Any) -> Persona:
    if not isinstance(raw, dict) or "role" not in raw:
        raise EnrichmentError(f"Persona '{name}' is missing or has no 'role'")
    return Persona(role=str(raw["role"]), why=str(raw.get("why", "")))


class PublicWebEnricher(Enricher):
    """Enriches accounts from public web data only (honesty rules apply)."""

    def __init__(self, client: ClaudeClient | None = None) -> None:
        self.client = client or ClaudeClient()

    def enrich(self, seed: SeedCompany, icp: ICPConfig) -> Account:
        data = self._extract_signals(seed, icp)
        factors = data.get("factors")
        if not isinstance(factors, dict):
            raise EnrichmentError("Model output has no 'factors' object")

        # _parse_factor(name, factors.get(name)) raises a clear EnrichmentError
        # naming any factor that is missing (None) or malformed.
        structural = StructuralScores(
            acuity=_parse_factor("acuity", factors.get("acuity")),
            roi_quant=_parse_factor("roi_quant", factors.get("roi_quant")),
            whitespace=_parse_factor("whitespace", factors.get("whitespace")),
            closeability=_parse_factor("closeability", factors.get("closeability")),
        )
        operational = OperationalScores(
            winnability=_parse_factor("winnability", factors.get("winnability")),
            active_pain_timing=_parse_factor(
                "active_pain_timing", factors.get("active_pain_timing")
            ),
            reachability=_parse_factor("reachability", factors.get("reachability")),
        )

        poc_angle = self.client.complete(
            "poc_angle",
            {
                "company_name": seed.name,
                "vendor_name": icp.vendor["name"],
                "vendor_description": icp.vendor["description"],
                "wedge": icp.wedge,
                "extracted_json": json.dumps(data, indent=2),
            },
            max_tokens=1024,
            label=seed.name,
        )
        if not poc_angle.strip():
            raise EnrichmentError(f"POC angle came back empty for {seed.name}")

        return Account(
            name=seed.name,
            segment=seed.segment,
            sub_segment=seed.sub_segment,
            hq=seed.hq,
            snapshot=str(data.get("snapshot", "")),
            structural=structural,
            operational=operational,
            final_score=0,  # scoring is a separate step (score.py)
            champion=_parse_persona("champion", data.get("champion")),
            economic_buyer=_parse_persona("economic_buyer", data.get("economic_buyer")),
            poc_angle=poc_angle,
            profile=seed.profile,
            registry=seed.registry,
        )

    def _extract_signals(self, seed: SeedCompany, icp: ICPConfig) -> dict[str, Any]:
        rubrics = "\n".join(
            f"- {name}: {text}" for name, text in icp.factor_rubrics.items()
        )
        raw = self.client.complete(
            "extract_signals",
            {
                "company_json": json.dumps(seed.to_dict(), indent=2),
                "vendor_name": icp.vendor["name"],
                "vendor_description": icp.vendor["description"],
                "wedge": icp.wedge,
                "rubrics": rubrics,
                "incumbents": json.dumps(icp.incumbents, indent=2),
            },
            web_search=True,
            max_tokens=8192,
            label=seed.name,
        )
        return parse_json_response(raw)
