"""Tests for the scoring model and Account JSON round-trip.

Run from the repo root:  python3 -m unittest discover tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Make the repo root importable no matter where unittest is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lender_engine.config import ScoringConfig, load_config
from lender_engine.models import (
    Account,
    Evidence,
    Factor,
    OperationalScores,
    Persona,
    StructuralScores,
)
from lender_engine.score import final_score, rank, score_account


def factor(value: float) -> Factor:
    return Factor(
        value=value,
        rationale="test rationale",
        evidence=[Evidence("test claim", "https://example.com", "sourced")],
    )


def account(name: str, structural_values: tuple, operational_values: tuple) -> Account:
    a, r, w, c = structural_values
    win, pain, reach = operational_values
    return Account(
        name=name,
        segment="thrift_bank",
        sub_segment="",
        hq="Testville",
        snapshot="A test account.",
        structural=StructuralScores(
            acuity=factor(a), roi_quant=factor(r), whitespace=factor(w), closeability=factor(c)
        ),
        operational=OperationalScores(
            winnability=factor(win),
            active_pain_timing=factor(pain),
            reachability=factor(reach),
        ),
        final_score=0,
        champion=Persona(role="Head of Credit Risk", why="owns the pain"),
        economic_buyer=Persona(role="COO", why="owns the budget"),
        poc_angle="Test POC angle.",
    )


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.cfg = ScoringConfig()

    def test_floor_behavior_zero_operational(self):
        """operational = 0 -> final = round(100 * structural_gate * floor)."""
        acc = account("FloorCo", (0.9, 0.8, 0.7, 1.0), (0.0, 0.0, 0.0))
        gate = (0.9 * 0.8 * 0.7 * 1.0) ** (1 / 4)  # geometric mean of the 4 factors
        expected = round(100 * gate * self.cfg.structural_floor)
        self.assertEqual(final_score(acc.structural, acc.operational, self.cfg), expected)

    def test_multiplicative_kill(self):
        """Any structural factor at 0 (incl. closeability) kills the account."""
        for zeroed in [
            (0.0, 1.0, 1.0, 1.0),
            (1.0, 0.0, 1.0, 1.0),
            (1.0, 1.0, 0.0, 1.0),
            (1.0, 1.0, 1.0, 0.0),
        ]:
            acc = account("KillCo", zeroed, (1.0, 1.0, 1.0))
            self.assertEqual(final_score(acc.structural, acc.operational, self.cfg), 0)

    def test_perfect_account_scores_100(self):
        acc = account("PerfectCo", (1.0, 1.0, 1.0, 1.0), (1.0, 1.0, 1.0))
        self.assertEqual(final_score(acc.structural, acc.operational, self.cfg), 100)

    def test_closeability_gates_unlicensed(self):
        """An account with a revoked licence is dragged far below its licensed twin."""
        us = account("LicensedTwin", (0.9, 0.9, 0.8, 1.0), (0.7, 0.7, 0.7))
        cn = account("RevokedTwin", (0.9, 0.9, 0.8, 0.15), (0.7, 0.7, 0.7))
        us_score = final_score(us.structural, us.operational, self.cfg)
        cn_score = final_score(cn.structural, cn.operational, self.cfg)
        self.assertLess(cn_score, us_score * 0.75)

    def test_closeability_override_applies(self):
        from lender_engine.config import ICPConfig, apply_closeability_override

        acc = account("OwnedCo", (0.9, 0.9, 0.8, 0.8), (0.7, 0.7, 0.7))
        icp = ICPConfig(
            name="t", wedge="w", factor_rubrics={}, incumbents={},
            scoring=self.cfg, seed_file="s.json",
            closeability_overrides={
                "OwnedCo": {"value": 0.15, "rationale": "parent group decides technology abroad", "source_url": "https://x"}
            },
        )
        before = final_score(acc.structural, acc.operational, self.cfg)
        apply_closeability_override(acc, icp)
        after = final_score(acc.structural, acc.operational, self.cfg)
        self.assertEqual(acc.structural.closeability.value, 0.15)
        self.assertEqual(acc.structural.closeability.evidence[0].confidence, "sourced")
        self.assertLess(after, before)

    def test_geo_tier_mapping(self):
        from lender_engine.config import geo_tier

        geo = {
            "tiers": {"us": 1.0, "allied": 0.8, "restricted": 0.15, "unknown": 0.5},
            "countries": {"USA": "us", "Sweden": "allied", "China": "restricted"},
        }
        self.assertEqual(geo_tier("Durham, NC, USA", geo), ("us", 1.0))
        self.assertEqual(geo_tier("Linkoping, Sweden", geo), ("allied", 0.8))
        self.assertEqual(geo_tier("Jinan, China", geo), ("restricted", 0.15))
        self.assertEqual(geo_tier("Atlantis", geo), ("unknown", 0.5))

    def test_default_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(self.cfg.weights.values()), 1.0)

    def test_operational_weighted_uses_config_weights(self):
        acc = account("WeightCo", (1.0, 1.0, 1.0, 1.0), (1.0, 0.0, 0.0))
        # Only winnability is non-zero -> weighted operational = 0.35.
        self.assertAlmostEqual(acc.operational.weighted(self.cfg.weights), 0.35)

    def test_ranking_order(self):
        strong = score_account(account("Strong", (1.0, 1.0, 0.9, 1.0), (0.9, 0.9, 0.9)), self.cfg)
        medium = score_account(account("Medium", (0.5, 1.0, 0.8, 0.8), (0.5, 0.5, 0.5)), self.cfg)
        weak = score_account(account("Weak", (0.3, 0.4, 0.5, 0.5), (0.2, 0.2, 0.2)), self.cfg)
        ranked = rank([weak, strong, medium])
        self.assertEqual([a.name for a in ranked], ["Strong", "Medium", "Weak"])
        self.assertTrue(ranked[0].final_score >= ranked[1].final_score >= ranked[2].final_score)

    def test_account_json_round_trip(self):
        original = score_account(
            account("RoundTripCo", (0.8, 0.9, 0.7, 1.0), (0.6, 0.7, 0.8)), self.cfg
        )
        restored = Account.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(restored, original)

    def test_non_default_config_changes_score(self):
        """A non-default floor/weights config changes the final score (hand-checked)."""
        acc = account("TunedCo", (1.0, 1.0, 1.0, 1.0), (0.8, 0.6, 0.4))
        tuned = ScoringConfig(
            weights={"winnability": 0.5, "active_pain_timing": 0.3, "reachability": 0.2},
            structural_floor=0.2,
        )
        # weighted = 0.8*0.5 + 0.6*0.3 + 0.4*0.2 = 0.66
        # multiplier = 0.2 + 0.8*0.66 = 0.728 -> round(100 * 1.0 * 0.728) = 73
        self.assertEqual(final_score(acc.structural, acc.operational, tuned), 73)
        # Default config yields a different score (77), proving the config drives it.
        self.assertEqual(final_score(acc.structural, acc.operational, self.cfg), 77)


class TestLoadConfig(unittest.TestCase):
    def test_bad_weights_dict_raises(self):
        """load_config rejects a partial/bad weights dict at load time."""
        bad = {
            "name": "Bad ICP",
            "wedge": "w",
            "factor_rubrics": {},
            "incumbents": {},
            "seed_file": "data/seed_companies.json",
            "scoring": {
                # Partial weights merge over defaults and no longer sum to 1.0.
                "weights": {"winnability": 0.5, "active_pain_timing": 0.5},
                "structural_floor": 0.4,
            },
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(bad, handle)
            path = handle.name
        try:
            with self.assertRaises(ValueError):
                load_config(path)
        finally:
            Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
