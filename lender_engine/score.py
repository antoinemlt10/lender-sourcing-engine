"""Account scoring.

final = round(100 * structural * (floor + (1 - floor) * operational))

- structural is the geometric mean of acuity, roi_quant, whitespace and
  closeability (the 4th root of their product). It stays multiplicative: a
  single zero factor still kills the account, and a weak factor drags hard,
  but the 0-100 scale stays readable: a raw multi-factor product would cap
  even a near-perfect real account around 60/100.
- operational is a weighted average of winnability, active pain timing and
  reachability.
- the floor (default 0.4) keeps structurally-excellent accounts visible even
  when we cannot yet see an operational opening.
"""

from __future__ import annotations

from lender_engine.config import ScoringConfig
from lender_engine.models import Account, OperationalScores, StructuralScores


def final_score(
    structural: StructuralScores,
    operational: OperationalScores,
    cfg: ScoringConfig,
) -> int:
    floor = cfg.structural_floor
    # Geometric mean of the structural factors: zero still kills.
    gate = structural.product() ** (1 / StructuralScores.FACTOR_COUNT)
    multiplier = floor + (1 - floor) * operational.weighted(cfg.weights)
    return round(100 * gate * multiplier)


def score_account(account: Account, cfg: ScoringConfig) -> Account:
    """Fill in final_score on an enriched account and return it."""
    account.final_score = final_score(account.structural, account.operational, cfg)
    return account


def rank(accounts: list[Account]) -> list[Account]:
    """Sort accounts by final_score, best first."""
    return sorted(accounts, key=lambda a: a.final_score, reverse=True)
