"""Distribution diagnostics on a synthetic ranked output. No network."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lender_engine.config import ScoringConfig
from lender_engine.diagnose import run_diagnostics, write_diagnostics
from lender_engine.models import (
    Account,
    Evidence,
    Factor,
    OperationalScores,
    Persona,
    StructuralScores,
)
from lender_engine.score import score_account


def _factor(v: float, sourced: bool) -> Factor:
    return Factor(v, "r", [Evidence("c", "https://x" if sourced else "", "sourced" if sourced else "inferred")])


def _account(name: str, segment: str, s: tuple, o: tuple, sourced: bool = True) -> Account:
    a = Account(
        name=name, segment=segment, sub_segment="", hq="PH", snapshot="s",
        structural=StructuralScores(_factor(s[0], sourced), _factor(s[1], sourced), _factor(s[2], sourced), _factor(s[3], sourced)),
        operational=OperationalScores(_factor(o[0], sourced), _factor(o[1], sourced), _factor(o[2], sourced)),
        final_score=0, champion=Persona("r", "w"), economic_buyer=Persona("r", "w"), poc_angle="a",
    )
    return score_account(a, ScoringConfig())


class TestDiagnose(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        # Four identical accounts (a 4-way tie) straddling a top-2 cut, plus
        # two distinct ones, plus one where every factor is inferred.
        accounts = [
            _account("Top", "digital_bank", (1, 1, 1, 1), (1, 1, 1)),
            *[_account(f"Tie{i}", "thrift_bank", (0.8, 0.8, 0.8, 1.0), (0.6, 0.6, 0.6)) for i in range(4)],
            _account("Low", "lending_company", (0.3, 0.4, 0.5, 1.0), (0.2, 0.2, 0.2), sourced=False),
        ]
        self.path = self.tmp / "ranked_accounts.json"
        self.path.write_text(json.dumps([a.to_dict() for a in accounts]), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_ties_and_boundary_are_reported(self):
        r = run_diagnostics(self.path, ScoringConfig(), top_k=2)
        self.assertEqual(r["ties"]["n"], 6)
        self.assertEqual(r["ties"]["distinct_scores"], 3)
        self.assertEqual(r["ties"]["largest_tie_groups"][0]["count"], 4)
        b = r["ties"]["boundary"]
        self.assertTrue(b["tied"])
        self.assertEqual(b["swap_set_size"], 4)
        self.assertEqual(len(b["inside"]), 1)
        self.assertEqual(len(b["outside"]), 3)

    def test_low_spread_factor_is_flagged(self):
        r = run_diagnostics(self.path, ScoringConfig(), top_k=2)
        # closeability is 1.0 everywhere: two distinct values at most, flagged.
        self.assertTrue(r["factors"]["closeability"]["low_spread"])

    def test_sourced_share_per_segment(self):
        r = run_diagnostics(self.path, ScoringConfig(), top_k=2)
        s = r["sourced"]
        self.assertEqual(s["per_segment"]["lending_company"]["share"], 0.0)
        self.assertEqual(s["per_segment"]["digital_bank"]["share"], 1.0)

    def test_stability_and_outputs(self):
        r = run_diagnostics(self.path, ScoringConfig(), top_k=2)
        self.assertEqual(len(r["stability"]["variants"]), 8)
        for v in r["stability"]["variants"]:
            self.assertGreaterEqual(v["spearman"], -1.0)
            self.assertLessEqual(v["top_k_jaccard"], 1.0)
        paths = write_diagnostics(r, self.tmp / "out")
        self.assertTrue(all(p.exists() for p in paths))
        md = paths[0].read_text(encoding="utf-8")
        self.assertIn("Top-2 boundary", md)
        self.assertIn("arbitrary", r["summary"])

    def test_csv_input_skips_sourced_section(self):
        from lender_engine.config import ICPConfig
        from lender_engine.render import write_outputs

        icp = ICPConfig(name="t", wedge="w", factor_rubrics={}, incumbents={}, scoring=ScoringConfig(), seed_file="s")
        accounts = [Account.from_dict(d) for d in json.loads(self.path.read_text(encoding="utf-8"))]
        write_outputs(accounts, str(self.tmp / "o"), icp)
        r = run_diagnostics(self.tmp / "o" / "ranked_accounts.csv", ScoringConfig(), top_k=2)
        self.assertIsNone(r["sourced"])
        self.assertEqual(r["ties"]["distinct_scores"], 3)


if __name__ == "__main__":
    unittest.main()
