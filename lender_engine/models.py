"""Typed data model.

Every dataclass supports a JSON round-trip via to_dict() / from_dict().
Scores: structural factors combine multiplicatively (a zero kills the
account), operational factors are a weighted average.

Invariants (confidence values, factor ranges) are enforced in __post_init__,
so they hold for every Evidence/Factor however it is constructed, including
from_dict at the deserialization boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# Every claim is either backed by a public source URL ("sourced")
# or is an educated guess we openly flag ("inferred").
Confidence = Literal["sourced", "inferred"]


@dataclass
class Evidence:
    """One cited claim supporting a factor value."""

    claim: str
    source_url: str
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.confidence not in ("sourced", "inferred"):
            raise ValueError(
                f"Evidence.confidence must be 'sourced' or 'inferred', got {self.confidence!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Evidence:
        return cls(
            claim=data["claim"],
            source_url=data["source_url"],
            confidence=data["confidence"],
        )


@dataclass
class Factor:
    """A single scoring factor: a 0-1 value plus why we believe it."""

    value: float  # 0.0 to 1.0
    rationale: str
    evidence: list[Evidence] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"Factor.value must be in [0.0, 1.0], got {self.value}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Factor:
        return cls(
            value=data["value"],
            rationale=data["rationale"],
            evidence=[Evidence.from_dict(e) for e in data.get("evidence", [])],
        )


@dataclass
class StructuralScores:
    """Is this fundamentally a good account? Three factors multiply: one zero
    kills it. Closeability is not part of the product: it is a binary
    eligibility gate (see score.py and ScoringConfig.closeability_min).

    Factor names are generic on purpose; what each one means for a given
    vendor is written in the ICP config's rubrics, not here.
    """

    acuity: Factor  # intensity of the pain the vendor removes
    roi_quant: Factor  # how directly that pain converts to money
    whitespace: Factor  # how free the account is of a locked-in incumbent
    closeability: Factor  # eligibility gate: licence, standing, jurisdiction

    FACTOR_COUNT = 3  # score.py takes the FACTOR_COUNT-th root (geometric mean)

    def product(self) -> float:
        return self.acuity.value * self.roi_quant.value * self.whitespace.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuralScores:
        return cls(
            acuity=Factor.from_dict(data["acuity"]),
            roi_quant=Factor.from_dict(data["roi_quant"]),
            whitespace=Factor.from_dict(data["whitespace"]),
            closeability=Factor.from_dict(data["closeability"]),
        )


@dataclass
class OperationalScores:
    """Can we win it now? A weighted average (weights come from config)."""

    winnability: Factor
    active_pain_timing: Factor
    reachability: Factor

    def weighted(self, weights: dict[str, float]) -> float:
        return (
            self.winnability.value * weights["winnability"]
            + self.active_pain_timing.value * weights["active_pain_timing"]
            + self.reachability.value * weights["reachability"]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationalScores:
        return cls(
            winnability=Factor.from_dict(data["winnability"]),
            active_pain_timing=Factor.from_dict(data["active_pain_timing"]),
            reachability=Factor.from_dict(data["reachability"]),
        )


@dataclass
class Persona:
    """A buying role (role level only, never an individual's name)."""

    role: str
    why: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Persona:
        return cls(role=data["role"], why=data["why"])


# How an account entered the pool. "prospect" is the default;
# "customer_reference" marks a known customer kept as a calibration point:
# it is scored through the same rubric as everyone else, never hand-forced.
Profile = Literal["prospect", "customer_reference"]


@dataclass
class Registry:
    """Where a seed came from: the public register that lists it.

    Every seed carries this so the pool itself is verifiable, not just the
    enrichment. as_of is the date printed on the register, not today's date.
    """

    source: str  # e.g. "SEC PH list of lending companies with CA"
    regulator: str  # e.g. "SEC", "BSP"
    url: str
    as_of: str  # YYYY-MM-DD as printed on the list, or "" if unknown
    registry_id: str = ""  # certificate / registration number if listed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Registry:
        return cls(
            source=data.get("source", ""),
            regulator=data.get("regulator", ""),
            url=data.get("url", ""),
            as_of=data.get("as_of", ""),
            registry_id=data.get("registry_id", ""),
        )


@dataclass
class SeedCompany:
    """A raw entry from the seed pool, before enrichment."""

    name: str
    segment: str  # entity type, e.g. "digital_bank", "thrift_bank", "lending_company"
    sub_segment: str  # free text refinement, e.g. "olp_registered"
    hq: str
    notes: str
    profile: Profile = "prospect"
    registry: Registry | None = None

    def __post_init__(self) -> None:
        if self.profile not in ("prospect", "customer_reference"):
            raise ValueError(f"SeedCompany.profile invalid: {self.profile!r}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.registry is None:
            data.pop("registry")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedCompany:
        registry = data.get("registry")
        return cls(
            name=data["name"],
            segment=data["segment"],
            sub_segment=data.get("sub_segment", ""),
            hq=data.get("hq", ""),
            notes=data.get("notes", ""),
            profile=data.get("profile", "prospect"),
            registry=Registry.from_dict(registry) if isinstance(registry, dict) else None,
        )


@dataclass
class Account:
    """A fully enriched and scored account."""

    name: str
    segment: str
    sub_segment: str
    hq: str
    snapshot: str
    structural: StructuralScores
    operational: OperationalScores
    final_score: int
    champion: Persona
    economic_buyer: Persona
    poc_angle: str
    profile: Profile = "prospect"
    registry: Registry | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.registry is None:
            data.pop("registry")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Account:
        registry = data.get("registry")
        return cls(
            name=data["name"],
            segment=data["segment"],
            sub_segment=data.get("sub_segment", ""),
            hq=data.get("hq", ""),
            snapshot=data.get("snapshot", ""),
            structural=StructuralScores.from_dict(data["structural"]),
            operational=OperationalScores.from_dict(data["operational"]),
            final_score=data["final_score"],
            champion=Persona.from_dict(data["champion"]),
            economic_buyer=Persona.from_dict(data["economic_buyer"]),
            poc_angle=data.get("poc_angle", ""),
            profile=data.get("profile", "prospect"),
            registry=Registry.from_dict(registry) if isinstance(registry, dict) else None,
        )
