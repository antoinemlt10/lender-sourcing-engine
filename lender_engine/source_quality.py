"""Reclassify evidence whose source cannot carry the claim.

A map listing, a social media page or a municipal business directory can
confirm that a lender exists and where it is. It cannot support a claim about
the lender's products, volumes, vendors, recent moves or reachability. The
config lists such domains under source_quality.existence_only_domains; every
evidence item that cites one of them as its source is reclassified from
"sourced" to "inferred". The claim and the URL are kept, so the reader can
still see what was found; only the confidence flag changes, and the share of
sourced evidence reported for the account drops accordingly.

Factor values are never touched here. The step runs after enrichment (so new
accounts are consistent) and on every re-rank (so stored accounts follow a
config change).
"""

from __future__ import annotations

from urllib.parse import urlparse

from lender_engine.config import ICPConfig
from lender_engine.models import Account


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def existence_only(url: str, icp: ICPConfig) -> bool:
    domains = icp.source_quality.get("existence_only_domains", [])
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in domains)


def apply_source_quality(account: Account, icp: ICPConfig) -> int:
    """Reclassify matching evidence in place; return how many items changed."""
    changed = 0
    for factors in (account.structural, account.operational):
        for factor in vars(factors).values():
            for evidence in getattr(factor, "evidence", []):
                if evidence.confidence == "sourced" and evidence.source_url and existence_only(evidence.source_url, icp):
                    evidence.confidence = "inferred"
                    changed += 1
    return changed
