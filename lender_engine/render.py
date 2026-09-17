"""Render ranked accounts to JSON, CSV and Markdown.

The Markdown is one shortlist (the accounts to talk to first) followed by
one section per entity type, so a reader can see how the ranking treats
banks against non-bank lenders. Every row shows the register the account
came from and how much of its evidence is sourced rather than inferred.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from lender_engine.config import ICPConfig
from lender_engine.models import Account, Factor

SHORTLIST_SIZE = 15
SEGMENT_LIST_SIZE = 12

FACTOR_NAMES = [
    "acuity",
    "roi_quant",
    "whitespace",
    "closeability",
    "winnability",
    "active_pain_timing",
    "reachability",
]

CSV_COLUMNS = [
    "name",
    "segment",
    "sub_segment",
    "profile",
    "hq",
    "final_score",
    *FACTOR_NAMES,
    "sourced_share",
    "champion_role",
    "economic_buyer_role",
    "poc_angle",
    "registry_source",
    "registry_regulator",
    "registry_id",
    "registry_as_of",
    "registry_url",
    "evidence_urls",
]


def factors_of(account: Account) -> dict[str, Factor]:
    """The seven scoring factors of an account, keyed by name."""
    return {
        "acuity": account.structural.acuity,
        "roi_quant": account.structural.roi_quant,
        "whitespace": account.structural.whitespace,
        "closeability": account.structural.closeability,
        "winnability": account.operational.winnability,
        "active_pain_timing": account.operational.active_pain_timing,
        "reachability": account.operational.reachability,
    }


def sourced_share(account: Account) -> float | None:
    """Share of evidence items flagged 'sourced' (None if no evidence at all)."""
    items = [e for f in factors_of(account).values() for e in f.evidence]
    if not items:
        return None
    return sum(1 for e in items if e.confidence == "sourced") / len(items)


def evidence_urls(account: Account) -> list[str]:
    urls: list[str] = []
    for factor in factors_of(account).values():
        for evidence in factor.evidence:
            if evidence.source_url and evidence.source_url not in urls:
                urls.append(evidence.source_url)
    return urls


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _csv_safe(value: object) -> str:
    """Guard against spreadsheet formula injection (=, +, -, @ prefixes)."""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def _first_sentence(text: str, max_words: int = 24) -> str:
    text = " ".join(text.split())
    for stop in (". ", "? ", "! "):
        idx = text.find(stop)
        if idx > 0:
            text = text[:idx]
            break
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    return text.rstrip(".,; ") + "."


def _write_json(accounts: list[Account], path: Path) -> None:
    path.write_text(json.dumps([a.to_dict() for a in accounts], indent=2), encoding="utf-8")


def _write_csv(accounts: list[Account], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for account in accounts:
            factors = factors_of(account)
            share = sourced_share(account)
            reg = account.registry
            row = {
                "name": account.name,
                "segment": account.segment,
                "sub_segment": account.sub_segment,
                "profile": account.profile,
                "hq": account.hq,
                "final_score": account.final_score,
                **{name: factors[name].value for name in FACTOR_NAMES},
                "sourced_share": "" if share is None else f"{share:.2f}",
                "champion_role": account.champion.role,
                "economic_buyer_role": account.economic_buyer.role,
                "poc_angle": account.poc_angle,
                "registry_source": reg.source if reg else "",
                "registry_regulator": reg.regulator if reg else "",
                "registry_id": reg.registry_id if reg else "",
                "registry_as_of": reg.as_of if reg else "",
                "registry_url": reg.url if reg else "",
                "evidence_urls": " ".join(evidence_urls(account)),
            }
            writer.writerow({k: _csv_safe(v) for k, v in row.items()})


def _row(rank: int, account: Account) -> str:
    share = sourced_share(account)
    share_txt = "n/a" if share is None else f"{int(round(share * 100))}%"
    reg = account.registry.regulator if account.registry else ""
    return (
        f"| {rank} | {_cell(account.name)} | {_cell(account.segment)} | {reg} | "
        f"{account.final_score} | {share_txt} | {_cell(account.champion.role)} | "
        f"{_cell(_first_sentence(account.poc_angle))} |"
    )


TABLE_HEADER = [
    "| # | Account | Entity type | Register | Score | Sourced | Champion role | Angle |",
    "|---|---------|-------------|----------|-------|---------|---------------|-------|",
]


def _write_markdown(accounts: list[Account], path: Path, icp: ICPConfig) -> None:
    prospects = [a for a in accounts if a.profile == "prospect"]
    references = [a for a in accounts if a.profile == "customer_reference"]
    rank_of = {a.name: i for i, a in enumerate(prospects, start=1)}

    lines = [
        f"# {icp.name}: ranked accounts",
        "",
        f"**{len(prospects)} accounts scored** against the rubric in the config. "
        "Closeability is an eligibility gate (below the config threshold the account "
        "scores 0). Structural gate = geometric mean of acuity, roi_quant and "
        "whitespace; operational readiness = weighted average of winnability, "
        "active_pain_timing and reachability. Every factor carries evidence flagged "
        "sourced or inferred; the *Sourced* column is the share of an account's "
        "evidence that has a public URL behind it.",
        "",
        "The pool comes from public regulator registers (see the register columns in "
        "the CSV). Rubrics are the ICP owner's hypothesis, not a description of the "
        "vendor's real pipeline; validate against closed/won data before acting on "
        "the order.",
        "",
    ]
    if references:
        lines.append("**Calibration references** (scored through the same rubric, excluded from the ranking):")
        for a in references:
            lines.append(f"- {_cell(a.name)}: {a.final_score}")
        lines.append("")

    lines += [f"## Talk to these first (top {min(SHORTLIST_SIZE, len(prospects))})", "", *TABLE_HEADER]
    for a in prospects[:SHORTLIST_SIZE]:
        lines.append(_row(rank_of[a.name], a))
    lines.append("")

    by_segment: dict[str, list[Account]] = defaultdict(list)
    for a in prospects:
        by_segment[a.segment].append(a)
    for segment, group in sorted(by_segment.items(), key=lambda kv: -len(kv[1])):
        lines += [f"## {segment} ({len(group)})", "", *TABLE_HEADER]
        for a in group[:SEGMENT_LIST_SIZE]:
            lines.append(_row(rank_of[a.name], a))
        if len(group) > SEGMENT_LIST_SIZE:
            lines.append(f"| | …plus {len(group) - SEGMENT_LIST_SIZE} more, see the CSV | | | | | | |")
        lines.append("")

    lines += [
        "*Full factor values, rationales, evidence URLs and register provenance are in "
        "`ranked_accounts.csv` and `ranked_accounts.json`. Run `python -m lender_engine "
        "diagnose` for the distribution checks (ties, factor variance, top-k stability).*",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(accounts: list[Account], out_dir: str, icp: ICPConfig) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "ranked_accounts.json"
    csv_path = out / "ranked_accounts.csv"
    md_path = out / "ranked_accounts.md"
    _write_json(accounts, json_path)
    _write_csv(accounts, csv_path)
    _write_markdown(accounts, md_path, icp)
    return [json_path, csv_path, md_path]


def write_brief(markdown: str, account_name: str, out_dir: str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slug = "".join(c.lower() if c.isalnum() else "_" for c in account_name).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    path = out / f"brief_{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
