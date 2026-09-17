"""Evidence citing an existence-only domain is reclassified to inferred."""

import unittest

from lender_engine.config import ICPConfig, ScoringConfig
from lender_engine.models import Account, Evidence, Factor, OperationalScores, Persona, StructuralScores
from lender_engine.source_quality import apply_source_quality


def _factor(url: str, confidence: str = "sourced") -> Factor:
    return Factor(value=0.5, rationale="r", evidence=[Evidence(claim="c", source_url=url, confidence=confidence)])


class TestSourceQuality(unittest.TestCase):
    def setUp(self):
        self.icp = ICPConfig(
            name="t", wedge="w", factor_rubrics={}, incumbents={}, scoring=ScoringConfig(),
            seed_file="x", vendor={"name": "v", "description": "d"},
            source_quality={"existence_only_domains": ["facebook.com", "waze.com"]},
        )
        self.account = Account(
            name="A", segment="thrift_bank", sub_segment="", hq="", snapshot="",
            structural=StructuralScores(
                acuity=_factor("https://www.facebook.com/p/A-Bank/"),
                roi_quant=_factor("https://waze.com/live-map/x"),
                whitespace=_factor("https://www.bsp.gov.ph/some.pdf"),
                closeability=_factor("https://m.facebook.com/abank", confidence="inferred"),
            ),
            operational=OperationalScores(
                winnability=_factor("https://facebook.com.evil.example/x"),
                active_pain_timing=_factor("", confidence="inferred"),
                reachability=_factor("https://ctb.com.ph/members/"),
            ),
            final_score=0, champion=Persona(role="r", why=""), economic_buyer=Persona(role="r", why=""),
            poc_angle="", profile="", registry=None,
        )

    def test_matching_sourced_items_become_inferred_values_untouched(self):
        changed = apply_source_quality(self.account, self.icp)
        self.assertEqual(changed, 2)  # facebook acuity, waze roi_quant
        self.assertEqual(self.account.structural.acuity.evidence[0].confidence, "inferred")
        self.assertEqual(self.account.structural.roi_quant.evidence[0].confidence, "inferred")
        self.assertEqual(self.account.structural.whitespace.evidence[0].confidence, "sourced")
        self.assertEqual(self.account.operational.reachability.evidence[0].confidence, "sourced")
        # a look-alike host is not a match; an already-inferred item is not counted
        self.assertEqual(self.account.operational.winnability.evidence[0].confidence, "sourced")
        self.assertEqual(self.account.structural.acuity.value, 0.5)
        # the URL is kept so the reader still sees what was found
        self.assertEqual(self.account.structural.acuity.evidence[0].source_url, "https://www.facebook.com/p/A-Bank/")
        self.assertEqual(apply_source_quality(self.account, self.icp), 0)  # idempotent

    def test_no_config_means_no_change(self):
        self.icp.source_quality = {}
        self.assertEqual(apply_source_quality(self.account, self.icp), 0)


if __name__ == "__main__":
    unittest.main()
