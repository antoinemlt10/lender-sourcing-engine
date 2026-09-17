"""Distribution checks on a ranked output.

A ranking can look sensible and still be close to random at the point
where it matters, the cut of a shortlist. These checks make that visible:

  ties          how many distinct scores there are, and the largest tie
                groups; a shortlist cut that falls inside a tie group is
                an arbitrary cut;
  boundary      whether the accounts at ranks k and k+1 share a score, and
                how many accounts sit on that score (the swap set);
  factors       mean, spread and number of distinct values per factor; a
                factor with almost no spread costs API calls and moves no one;
  sourced       the share of evidence items that have a public URL behind
                them, overall, per factor and per entity type; a segment
                that is mostly inferred is a segment the ranking does not
                know much about;
  stability     re-score from the stored factor values under small
                perturbations of the operational weights and the structural
                floor, and measure how much of the top-k survives (Jaccard)
                and how the full order moves (Spearman); an order that
                changes a lot under a 0.1 shift in one weight is an order
                that encodes the config more than the accounts.

Input is ranked_accounts.json (full evidence) or ranked_accounts.csv
(factor values only; the sourced-share section is then skipped).
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from typing import Any

from lender_engine.config import ScoringConfig
from lender_engine.models import Account, Evidence
from lender_engine.score import final_score

FACTOR_NAMES = [
    "acuity",
    "roi_quant",
    "whitespace",
    "closeability",
    "winnability",
    "active_pain_timing",
    "reachability",
]
STRUCTURAL = FACTOR_NAMES[:4]
OPERATIONAL = FACTOR_NAMES[4:]

PERTURBATION = 0.10
LOW_SPREAD_SD = 0.08
LOW_DISTINCT = 3


# ---------------------------------------------------------------- loading


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    """Rows with name, segment, profile, final_score, the 7 factor values,
    and (JSON only) an evidence list per factor."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        accounts = [Account.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
        rows = []
        for a in accounts:
            f = {
                "acuity": a.structural.acuity,
                "roi_quant": a.structural.roi_quant,
                "whitespace": a.structural.whitespace,
                "closeability": a.structural.closeability,
                "winnability": a.operational.winnability,
                "active_pain_timing": a.operational.active_pain_timing,
                "reachability": a.operational.reachability,
            }
            rows.append(
                {
                    "name": a.name,
                    "segment": a.segment,
                    "profile": a.profile,
                    "final_score": a.final_score,
                    "factors": {k: v.value for k, v in f.items()},
                    "evidence": {k: list(v.evidence) for k, v in f.items()},
                }
            )
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        rows = []
        for rec in csv.DictReader(handle):
            try:
                factors = {k: float(rec[k]) for k in FACTOR_NAMES}
            except (KeyError, ValueError) as exc:
                raise ValueError(f"{path}: row {rec.get('name')!r} lacks numeric factor columns ({exc})") from exc
            rows.append(
                {
                    "name": rec["name"],
                    "segment": rec.get("segment", ""),
                    "profile": rec.get("profile", "prospect"),
                    "final_score": int(float(rec["final_score"])),
                    "factors": factors,
                    "evidence": None,
                }
            )
        return rows


# ---------------------------------------------------------------- scoring from factors


class _S:
    def __init__(self, f: dict[str, float]):
        self._f = f

    def product(self) -> float:
        return self._f["acuity"] * self._f["roi_quant"] * self._f["whitespace"] * self._f["closeability"]

    FACTOR_COUNT = 4


class _O:
    def __init__(self, f: dict[str, float]):
        self._f = f

    def weighted(self, w: dict[str, float]) -> float:
        return sum(self._f[k] * w[k] for k in OPERATIONAL)


def _score(f: dict[str, float], cfg: ScoringConfig) -> int:
    return final_score(_S(f), _O(f), cfg)  # type: ignore[arg-type]


def _order(rows: list[dict[str, Any]], cfg: ScoringConfig) -> list[tuple[str, int]]:
    scored = [(r["name"], _score(r["factors"], cfg)) for r in rows]
    # Stable sort on name breaks ties deterministically so that two runs of
    # the same config give the same order; the boundary check reports how
    # arbitrary that tie-break is.
    return sorted(scored, key=lambda t: (-t[1], t[0]))


# ---------------------------------------------------------------- checks


def _ties(order: list[tuple[str, int]], top_k: int) -> dict[str, Any]:
    scores = [s for _, s in order]
    counts = Counter(scores)
    groups = sorted(
        ({"score": s, "count": c, "names": [n for n, sc in order if sc == s]} for s, c in counts.items() if c > 1),
        key=lambda g: (-g["count"], -g["score"]),
    )
    boundary: dict[str, Any] = {"top_k": top_k, "tied": False}
    if 0 < top_k < len(order):
        s_in, s_out = order[top_k - 1][1], order[top_k][1]
        if s_in == s_out:
            names = [n for n, sc in order if sc == s_in]
            inside = [n for n, _ in order[:top_k] if n in names]
            boundary = {
                "top_k": top_k,
                "tied": True,
                "score": s_in,
                "swap_set_size": len(names),
                "inside": inside,
                "outside": [n for n in names if n not in inside],
            }
    return {
        "n": len(order),
        "distinct_scores": len(counts),
        "distinct_ratio": round(len(counts) / len(order), 3) if order else 0.0,
        "largest_tie_groups": groups[:6],
        "accounts_in_ties": sum(c for c in counts.values() if c > 1),
        "boundary": boundary,
    }


def _factor_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in FACTOR_NAMES:
        vals = [r["factors"][k] for r in rows]
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        distinct = len(set(round(v, 3) for v in vals))
        out[k] = {
            "mean": round(statistics.mean(vals), 3),
            "sd": round(sd, 3),
            "min": round(min(vals), 3),
            "max": round(max(vals), 3),
            "distinct": distinct,
            "low_spread": sd < LOW_SPREAD_SD or distinct <= LOW_DISTINCT,
        }
    return out


def _sourced(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if any(r["evidence"] is None for r in rows):
        return None
    total = Counter()
    per_factor: dict[str, Counter] = defaultdict(Counter)
    per_segment: dict[str, Counter] = defaultdict(Counter)
    no_evidence = 0
    for r in rows:
        items: list[Evidence] = [e for k in FACTOR_NAMES for e in r["evidence"][k]]
        if not items:
            no_evidence += 1
        for k in FACTOR_NAMES:
            for e in r["evidence"][k]:
                per_factor[k][e.confidence] += 1
                per_segment[r["segment"]][e.confidence] += 1
                total[e.confidence] += 1

    def share(c: Counter) -> float | None:
        n = c["sourced"] + c["inferred"]
        return round(c["sourced"] / n, 3) if n else None

    return {
        "overall": share(total),
        "evidence_items": total["sourced"] + total["inferred"],
        "accounts_without_evidence": no_evidence,
        "per_factor": {k: {"share": share(c), "items": c["sourced"] + c["inferred"]} for k, c in per_factor.items()},
        "per_segment": {k: {"share": share(c), "items": c["sourced"] + c["inferred"]} for k, c in per_segment.items()},
    }


def _spearman(base: list[str], other: list[str]) -> float:
    n = len(base)
    if n < 2:
        return 1.0
    rank_b = {name: i for i, name in enumerate(base)}
    rank_o = {name: i for i, name in enumerate(other)}
    d2 = sum((rank_b[name] - rank_o[name]) ** 2 for name in base)
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return round(len(sa & sb) / len(sa | sb), 3) if sa | sb else 1.0


def _perturbed_configs(cfg: ScoringConfig) -> list[tuple[str, ScoringConfig]]:
    """One config per single-weight shift of +/- PERTURBATION (renormalized),
    plus the floor shifted by +/- PERTURBATION."""
    variants: list[tuple[str, ScoringConfig]] = []
    for k, sign in product(OPERATIONAL, (+1, -1)):
        w = dict(cfg.weights)
        w[k] = min(1.0, max(0.0, w[k] + sign * PERTURBATION))
        total = sum(w.values())
        if total <= 0:
            continue
        w = {kk: v / total for kk, v in w.items()}
        variants.append((f"{k} {'+' if sign > 0 else '-'}{PERTURBATION:.2f}", ScoringConfig(weights=w, structural_floor=cfg.structural_floor)))
    for sign in (+1, -1):
        floor = min(1.0, max(0.0, cfg.structural_floor + sign * PERTURBATION))
        variants.append((f"floor {'+' if sign > 0 else '-'}{PERTURBATION:.2f}", ScoringConfig(weights=dict(cfg.weights), structural_floor=floor)))
    return variants


def _stability(rows: list[dict[str, Any]], cfg: ScoringConfig, top_k: int) -> dict[str, Any]:
    base = _order(rows, cfg)
    base_names = [n for n, _ in base]
    base_top = base_names[:top_k]
    results = []
    for label, variant in _perturbed_configs(cfg):
        order = _order(rows, variant)
        names = [n for n, _ in order]
        top = names[:top_k]
        results.append(
            {
                "perturbation": label,
                "top_k_jaccard": _jaccard(base_top, top),
                "top_k_kept": len(set(base_top) & set(top)),
                "spearman": _spearman(base_names, names),
                "dropped": [n for n in base_top if n not in top],
                "entered": [n for n in top if n not in base_top],
            }
        )
    worst = min(results, key=lambda r: r["top_k_jaccard"]) if results else None
    return {
        "top_k": top_k,
        "perturbation": PERTURBATION,
        "baseline_top_k": base_top,
        "variants": results,
        "min_top_k_jaccard": worst["top_k_jaccard"] if worst else None,
        "worst_variant": worst["perturbation"] if worst else None,
        "min_spearman": min(r["spearman"] for r in results) if results else None,
    }


# ---------------------------------------------------------------- entry points


def run_diagnostics(ranked_path: str | Path, cfg: ScoringConfig, top_k: int = 15) -> dict[str, Any]:
    # Anything that is not a calibration reference is a prospect.
    rows = [r for r in _load_rows(ranked_path) if r["profile"] != "customer_reference"]
    if not rows:
        raise ValueError(f"{ranked_path}: no prospect accounts to diagnose")
    # Recompute from stored factors with the given config so the checks
    # describe this config, whether or not the file was rendered with it.
    order = _order(rows, cfg)
    stored = {r["name"]: r["final_score"] for r in rows}
    drift = [(n, stored[n], s) for n, s in order if stored[n] != s]
    result = {
        "source": str(ranked_path),
        "config": {"weights": cfg.weights, "structural_floor": cfg.structural_floor},
        "score_drift_from_file": drift[:10],
        "ties": _ties(order, top_k),
        "factors": _factor_stats(rows),
        "sourced": _sourced(rows),
        "stability": _stability(rows, cfg, top_k),
    }
    result["summary"] = _summary(result)
    return result


def _summary(r: dict[str, Any]) -> str:
    t, st = r["ties"], r["stability"]
    parts = [
        f"{t['n']} accounts, {t['distinct_scores']} distinct scores "
        f"({t['accounts_in_ties']} accounts share a score with at least one other).",
    ]
    b = t["boundary"]
    if b.get("tied"):
        parts.append(
            f"The top-{b['top_k']} cut falls inside a tie at {b['score']}: "
            f"{b['swap_set_size']} accounts share it, {len(b['outside'])} sit just outside. "
            "The cut is arbitrary there."
        )
    else:
        parts.append(f"The top-{b['top_k']} cut does not fall inside a tie.")
    low = [k for k, v in r["factors"].items() if v["low_spread"]]
    parts.append(
        f"Low-spread factors: {', '.join(low) if low else 'none'}."
    )
    if r["sourced"] and r["sourced"]["overall"] is not None:
        parts.append(f"Sourced evidence: {int(round(r['sourced']['overall'] * 100))}% of items have a public URL.")
    if st["min_top_k_jaccard"] is not None:
        parts.append(
            f"Stability: a {st['perturbation']:.2f} shift in one weight keeps at least "
            f"{int(round(st['min_top_k_jaccard'] * 100))}% of the top-{st['top_k']} (worst: {st['worst_variant']}); "
            f"full-order Spearman >= {st['min_spearman']}."
        )
    return " ".join(parts)


def _md(r: dict[str, Any]) -> str:
    t, f, s, st = r["ties"], r["factors"], r["sourced"], r["stability"]
    lines = [
        "# Distribution diagnostics",
        "",
        f"Source: `{r['source']}` · weights {r['config']['weights']} · floor {r['config']['structural_floor']}",
        "",
        r["summary"],
        "",
        "## Ties",
        "",
        f"- Accounts: {t['n']} · distinct scores: {t['distinct_scores']} ({int(t['distinct_ratio']*100)}%)",
        f"- Accounts sharing a score: {t['accounts_in_ties']}",
        "",
        "| Score | Count | Accounts |",
        "|------:|------:|----------|",
    ]
    for g in t["largest_tie_groups"]:
        lines.append(f"| {g['score']} | {g['count']} | {', '.join(g['names'])} |")
    b = t["boundary"]
    lines += ["", f"### Top-{b['top_k']} boundary", ""]
    if b.get("tied"):
        lines += [
            f"The accounts at ranks {b['top_k']} and {b['top_k']+1} both score {b['score']}. "
            f"{b['swap_set_size']} accounts share that score: inside the cut {', '.join(b['inside'])}; "
            f"outside {', '.join(b['outside'])}. Which of them are in the shortlist is a tie-break, not a finding.",
        ]
    else:
        lines.append("No tie at the boundary.")
    lines += ["", "## Factor spread", "", "| Factor | Mean | SD | Min | Max | Distinct | Flag |", "|---|---:|---:|---:|---:|---:|---|"]
    for k, v in f.items():
        lines.append(f"| {k} | {v['mean']} | {v['sd']} | {v['min']} | {v['max']} | {v['distinct']} | {'low spread' if v['low_spread'] else ''} |")
    lines += ["", "## Sourced vs inferred", ""]
    if s is None:
        lines.append("Not available from a CSV input; run on `ranked_accounts.json`.")
    else:
        lines += [
            f"- Evidence items: {s['evidence_items']} · sourced overall: "
            f"{'n/a' if s['overall'] is None else str(int(round(s['overall']*100)))+'%'} · accounts with no evidence at all: {s['accounts_without_evidence']}",
            "",
            "| Factor | Sourced | Items |",
            "|---|---:|---:|",
        ]
        for k, v in s["per_factor"].items():
            lines.append(f"| {k} | {'n/a' if v['share'] is None else str(int(round(v['share']*100)))+'%'} | {v['items']} |")
        lines += ["", "| Entity type | Sourced | Items |", "|---|---:|---:|"]
        for k, v in s["per_segment"].items():
            lines.append(f"| {k} | {'n/a' if v['share'] is None else str(int(round(v['share']*100)))+'%'} | {v['items']} |")
    lines += [
        "",
        f"## Top-{st['top_k']} stability under ±{st['perturbation']:.2f} shifts",
        "",
        "| Perturbation | Top-k kept | Jaccard | Spearman | Dropped | Entered |",
        "|---|---:|---:|---:|---|---|",
    ]
    for v in st["variants"]:
        lines.append(
            f"| {v['perturbation']} | {v['top_k_kept']}/{st['top_k']} | {v['top_k_jaccard']} | {v['spearman']} | "
            f"{', '.join(v['dropped']) or ''} | {', '.join(v['entered']) or ''} |"
        )
    if r["score_drift_from_file"]:
        lines += ["", "## Note", "", "Scores in the file differ from scores recomputed with this config for: "
                  + ", ".join(f"{n} ({a} in file, {b} recomputed)" for n, a, b in r["score_drift_from_file"])]
    lines.append("")
    return "\n".join(lines)


def write_diagnostics(result: dict[str, Any], out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "diagnostics.json"
    md_path = out / "diagnostics.md"
    serializable = json.loads(json.dumps(result, default=lambda o: o.to_dict() if hasattr(o, "to_dict") else str(o)))
    json_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    md_path.write_text(_md(result), encoding="utf-8")
    return [md_path, json_path]
