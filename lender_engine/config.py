"""ICP and scoring configuration, loaded from a JSON file.

All scoring knobs (operational weights, structural floor) live here so the
model can be tuned without touching code. load_config validates the config at
load time, before any enrichment spend, and load_seeds reads the seed pool.
Neither function imports the enrichment/LLM stack, so the offline `seed`
command never needs the anthropic dependency installed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from lender_engine.models import Account, Evidence, Factor, SeedCompany

WEIGHT_KEYS = frozenset({"winnability", "active_pain_timing", "reachability"})


def _default_weights() -> dict[str, float]:
    return {"winnability": 0.35, "active_pain_timing": 0.35, "reachability": 0.30}


@dataclass
class ScoringConfig:
    """Knobs for the final-score formula (the only source of defaults)."""

    weights: dict[str, float] = field(default_factory=_default_weights)
    structural_floor: float = 0.4  # keeps structurally-excellent accounts visible


@dataclass
class ICPConfig:
    """One ideal-customer-profile definition (wedge, rubrics, incumbents, seeds)."""

    name: str
    wedge: str
    factor_rubrics: dict[str, str]  # keys = the 7 factor names
    incumbents: dict[str, list[str]]  # segment -> incumbent vendor names
    scoring: ScoringConfig
    seed_file: str
    # Who we are sourcing for: {"name": "...", "description": "what they sell,
    # to whom, in one paragraph"}. Prompts read this; nothing vendor-specific
    # is hardcoded in the code or the prompt files.
    vendor: dict[str, str] = field(default_factory=dict)
    # Geo tiering for the closeability gate and the tiered output:
    # {"tiers": {"us": 1.0, "allied": 0.8, ...}, "countries": {"USA": "us", ...}}
    geo_tiers: dict = field(default_factory=dict)
    # Per-account closeability overrides for what an HQ-country map cannot
    # see (foreign/state ownership, offshore manufacturing):
    # {"<account name>": {"value": 0.15, "rationale": "...", "source_url": "..."}}
    closeability_overrides: dict = field(default_factory=dict)


def apply_closeability_override(account: Account, icp: ICPConfig) -> Account:
    """Replace closeability with the config override for this account, if any.

    Catches what neither an HQ-country map nor a web enrichment reliably
    sees: foreign/state ownership (e.g. a Dutch HQ owned by an entity-listed
    Chinese group) or manufacturing that sits in a restricted geography.
    Mutates and returns the account; re-score afterwards.
    """
    override = icp.closeability_overrides.get(account.name)
    if override:
        source_url = override.get("source_url", "")
        account.structural.closeability = Factor(
            value=float(override["value"]),
            rationale=f"Config override: {override['rationale']}",
            evidence=[
                Evidence(
                    claim="Ownership / manufacturing-geography override (see rationale)",
                    source_url=source_url,
                    confidence="sourced" if source_url else "inferred",
                )
            ],
        )
    return account


def geo_tier(hq: str, geo_tiers: dict) -> tuple[str, float]:
    """Map an HQ string to (tier name, closeability anchor) via its country.

    The country is taken as the last comma-separated token of hq. Unknown
    countries land in tier "unknown" with a conservative 0.5 anchor.
    """
    country = hq.rsplit(",", 1)[-1].strip()
    tier = geo_tiers.get("countries", {}).get(country, "unknown")
    factor = geo_tiers.get("tiers", {}).get(tier, 0.5)
    return tier, factor


def _validate_scoring(scoring: ScoringConfig, path: str | Path) -> None:
    """Fail fast on a malformed scoring config, naming the offending key."""
    weights = scoring.weights
    if set(weights) != set(WEIGHT_KEYS):
        raise ValueError(
            f"{path}: scoring.weights keys must be exactly {sorted(WEIGHT_KEYS)}, "
            f"got {sorted(weights)}"
        )
    for key, value in weights.items():
        # bool is an int subclass; reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: scoring.weights[{key!r}] must be numeric, got {value!r}")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{path}: scoring.weights[{key!r}] must be in [0, 1], got {value}")
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{path}: scoring.weights must sum to 1.0, got {total}")
    floor = scoring.structural_floor
    if isinstance(floor, bool) or not isinstance(floor, (int, float)):
        raise ValueError(f"{path}: scoring.structural_floor must be numeric, got {floor!r}")
    if not 0.0 <= floor <= 1.0:
        raise ValueError(f"{path}: scoring.structural_floor must be in [0, 1], got {floor}")


def load_config(path: str | Path) -> ICPConfig:
    """Read and validate an ICPConfig from JSON (see configs/kita_philippines_icp.json).

    User-supplied weights are merged over the dataclass defaults, then the
    whole scoring block is validated. Raises ValueError (naming the config
    path and offending key) before any enrichment work begins.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    scoring_raw = raw.get("scoring", {})

    defaults = ScoringConfig()  # single source of defaults
    weights = dict(defaults.weights)
    weights.update(scoring_raw.get("weights", {}))
    scoring = ScoringConfig(
        weights=weights,
        structural_floor=scoring_raw.get("structural_floor", defaults.structural_floor),
    )
    _validate_scoring(scoring, path)

    # A relative seed_file is resolved against the config file's directory,
    # so every command works from any cwd and a swapped ICP config can ship
    # its own seed file alongside it.
    seed_file = Path(raw["seed_file"])
    if not seed_file.is_absolute():
        seed_file = (Path(path).resolve().parent / seed_file).resolve()

    vendor = raw.get("vendor", {})
    if not isinstance(vendor, dict) or not vendor.get("name") or not vendor.get("description"):
        raise ValueError(f"{path}: 'vendor' must be an object with 'name' and 'description'")

    return ICPConfig(
        name=raw["name"],
        wedge=raw["wedge"],
        factor_rubrics=raw["factor_rubrics"],
        vendor=vendor,
        incumbents=raw["incumbents"],
        scoring=scoring,
        seed_file=str(seed_file),
        geo_tiers=raw.get("geo_tiers", {}),
        closeability_overrides=raw.get("closeability_overrides", {}),
    )


def load_seeds(seed_file: str | Path) -> list[SeedCompany]:
    """Load the seed company pool from a bare JSON list of company dicts."""
    raw = json.loads(Path(seed_file).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"{seed_file}: expected a JSON list of seed companies, got {type(raw).__name__}"
        )
    seeds: list[SeedCompany] = []
    for i, item in enumerate(raw):
        try:
            seeds.append(SeedCompany.from_dict(item))
        except (KeyError, TypeError) as exc:
            raise ValueError(f"{seed_file}: seed record at index {i} is malformed ({exc})") from exc
    return seeds
