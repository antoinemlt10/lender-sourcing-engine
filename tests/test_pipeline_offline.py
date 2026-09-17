"""End-to-end pipeline test with a fake enricher, no API, no network.

Runs run_pipeline against a hand-built FakeEnricher (implementing the Enricher
Protocol) over a temp seed file, then asserts the JSON/CSV/Markdown outputs
exist and are well-formed and that the SQLite store round-trips.

Run from the repo root:  python3 -m unittest discover tests -v
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lender_engine.config import ICPConfig, ScoringConfig
from lender_engine.enrich import Enricher
from lender_engine.models import (
    Account,
    Evidence,
    Factor,
    OperationalScores,
    Persona,
    SeedCompany,
    StructuralScores,
)
from lender_engine.pipeline import run_pipeline
from lender_engine.store import AccountStore


def _factor(value: float) -> Factor:
    return Factor(
        value=value,
        rationale="fake rationale",
        evidence=[Evidence("fake claim", "https://example.com/a", "sourced")],
    )


class FakeEnricher:
    """Deterministic offline Enricher: turns a seed into a fixed Account."""

    def enrich(self, seed: SeedCompany, icp: ICPConfig) -> Account:
        return Account(
            name=seed.name,
            segment=seed.segment,
            sub_segment=seed.sub_segment,
            hq=seed.hq,
            snapshot=f"{seed.name} is a fake test account.",
            structural=StructuralScores(
                acuity=_factor(0.8),
                roi_quant=_factor(0.9),
                whitespace=_factor(0.7),
                closeability=_factor(1.0),
            ),
            operational=OperationalScores(
                winnability=_factor(0.6),
                active_pain_timing=_factor(0.7),
                reachability=_factor(0.5),
            ),
            final_score=0,  # pipeline scores it
            champion=Persona(role="Head of Credit Risk", why="owns the pain"),
            economic_buyer=Persona(role="COO", why="owns the budget"),
            poc_angle=f"A bounded POC for {seed.name}.",
        )


class TestPipelineOffline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.db_path = str(tmp / "accounts.db")
        self.out_dir = str(tmp / "outputs")

        seeds = [
            {
                "name": f"SeedCo {i}",
                "segment": "thrift_bank",
                "sub_segment": "",
                "hq": "Testville",
                "notes": "n/a",
            }
            for i in range(1, 4)
        ]
        self.seed_file = tmp / "seeds.json"
        self.seed_file.write_text(json.dumps(seeds), encoding="utf-8")

        self.icp = ICPConfig(
            name="Test ICP",
            wedge="test wedge",
            factor_rubrics={},
            incumbents={},
            scoring=ScoringConfig(),
            seed_file=str(self.seed_file),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_fake_enricher_conforms_to_protocol(self):
        # Enricher is @runtime_checkable, so structural conformance is testable.
        self.assertIsInstance(FakeEnricher(), Enricher)

    def test_run_pipeline_produces_wellformed_outputs(self):
        ranked = run_pipeline(
            self.icp,
            db_path=self.db_path,
            out_dir=self.out_dir,
            enricher=FakeEnricher(),
        )
        self.assertEqual(len(ranked), 3)
        self.assertTrue(all(a.final_score > 0 for a in ranked))

        out = Path(self.out_dir)
        json_path = out / "ranked_accounts.json"
        csv_path = out / "ranked_accounts.csv"
        md_path = out / "ranked_accounts.md"
        for path in (json_path, csv_path, md_path):
            self.assertTrue(path.exists(), f"missing output: {path}")

        # JSON: well-formed and round-trips back into Accounts.
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 3)
        restored = [Account.from_dict(d) for d in data]
        self.assertEqual({a.name for a in restored}, {"SeedCo 1", "SeedCo 2", "SeedCo 3"})

        # CSV: header + 3 rows.
        with csv_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)

        # Markdown: carries the ICP-derived title.
        md = md_path.read_text(encoding="utf-8")
        self.assertIn("# Test ICP: ranked accounts", md)

        # DB round-trips.
        with AccountStore(self.db_path) as store:
            stored = store.all_accounts()
            one = store.get("SeedCo 1")
        self.assertEqual(len(stored), 3)
        self.assertIsNotNone(one)

    def test_all_failures_raise_and_do_not_clobber(self):
        from lender_engine.pipeline import PipelineError

        class ExplodingEnricher:
            def enrich(self, seed, icp):
                raise RuntimeError("boom")

        with self.assertRaises(PipelineError):
            run_pipeline(
                self.icp,
                db_path=self.db_path,
                out_dir=self.out_dir,
                enricher=ExplodingEnricher(),
            )
        # No outputs written on total failure.
        self.assertFalse((Path(self.out_dir) / "ranked_accounts.json").exists())

    def test_only_names_restricts_the_run(self):
        ranked = run_pipeline(
            self.icp,
            db_path=self.db_path,
            out_dir=self.out_dir,
            enricher=FakeEnricher(),
            only_names=["SeedCo 2", "SeedCo 3", "Not A Seed"],
        )
        self.assertEqual(sorted(a.name for a in ranked), ["SeedCo 2", "SeedCo 3"])
        # --only and --skip compose: skip wins for a name in both.
        ranked = run_pipeline(
            self.icp,
            db_path=self.db_path,
            out_dir=self.out_dir,
            enricher=FakeEnricher(),
            only_names=["SeedCo 1", "SeedCo 2"],
            skip_names=["SeedCo 2"],
        )
        # The store now holds 1, 2 and 3; the rendered ranking is the whole store.
        self.assertEqual(sorted(a.name for a in ranked), ["SeedCo 1", "SeedCo 2", "SeedCo 3"])


if __name__ == "__main__":
    unittest.main()
