"""Command-line interface for the lender sourcing engine."""

import argparse
import sys
from pathlib import Path

# Anchor the default config to the repo root so `--config` works from any cwd.
# db/outputs stay cwd-relative (they are user working files, not repo assets).
_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = str(_REPO_ROOT / "configs" / "kita_philippines_icp.json")
DEFAULT_DB = "lenders.db"
DEFAULT_OUT = "outputs"


def _nonneg_int(value: str) -> int:
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {ivalue}")
    return ivalue


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lender_engine",
        description="Source lenders from public registers, enrich, score against an ICP, rank and diagnose.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the full pipeline: seed -> enrich -> score -> render.")
    run_p.add_argument(
        "--limit", type=_nonneg_int, default=None, help="Only process the first N seeds (N >= 0)."
    )
    run_p.add_argument("--config", default=DEFAULT_CONFIG, help="Path to the ICP config JSON.")
    run_p.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite account store.")
    run_p.add_argument("--out", default=DEFAULT_OUT, help="Output directory.")
    run_p.add_argument(
        "--skip-enriched", action="store_true",
        help="Skip seeds already in the store (resume an interrupted run, no re-spend).",
    )
    run_p.add_argument(
        "--skip", action="append", default=[], metavar="NAME",
        help="Skip this seed by name (repeatable) (for example defer predictable low-scorers).",
    )

    rank_p = sub.add_parser(
        "rank", help="Re-score (with the current config) and re-render stored accounts."
    )
    rank_p.add_argument("--config", default=DEFAULT_CONFIG, help="Path to the ICP config JSON.")
    rank_p.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite account store.")
    rank_p.add_argument("--out", default=DEFAULT_OUT, help="Output directory.")

    brief_p = sub.add_parser("brief", help="Generate a deep brief for a stored account.")
    brief_p.add_argument(
        "name", nargs="?", default=None,
        help="Account name (default: the top-ranked stored account).",
    )
    brief_p.add_argument("--config", default=DEFAULT_CONFIG, help="Path to the ICP config JSON.")
    brief_p.add_argument("--db", default=DEFAULT_DB, help="Path to the SQLite account store.")
    brief_p.add_argument("--out", default=DEFAULT_OUT, help="Output directory.")

    seed_p = sub.add_parser("seed", help="List the seed company pool.")
    seed_p.add_argument("--config", default=DEFAULT_CONFIG, help="Path to the ICP config JSON.")

    src_p = sub.add_parser(
        "sources", help="Build the seed pool from public regulator registers (no API calls)."
    )
    src_p.add_argument(
        "--manifest", default=str(_REPO_ROOT / "registries" / "manifest.json"),
        help="Register manifest (which lists, where, as of when).",
    )
    src_p.add_argument(
        "--out", default=str(_REPO_ROOT / "data" / "seed_lenders.json"),
        help="Seed pool to write.",
    )
    src_p.add_argument(
        "--inspect", action="store_true",
        help="Print the first rows of each register file and exit (to map columns).",
    )

    diag_p = sub.add_parser(
        "diagnose", help="Distribution checks on a ranked output: ties, variance, top-k stability."
    )
    diag_p.add_argument("--config", default=DEFAULT_CONFIG, help="Path to the ICP config JSON.")
    diag_p.add_argument(
        "--ranked", default=None,
        help="ranked_accounts.json (or .csv) to check; defaults to <out>/ranked_accounts.json.",
    )
    diag_p.add_argument("--out", default=DEFAULT_OUT, help="Output directory.")
    diag_p.add_argument("--top", type=int, default=15, help="Shortlist size to test (default 15).")

    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    from lender_engine.config import load_config
    from lender_engine.pipeline import PipelineError, run_pipeline

    icp = load_config(args.config)
    try:
        accounts = run_pipeline(
            icp, limit=args.limit, db_path=args.db, out_dir=args.out,
            skip_enriched=args.skip_enriched, skip_names=args.skip,
        )
    except PipelineError as exc:
        print(f"Pipeline failed: {exc}")
        return 1
    print(f"Done: {len(accounts)} accounts ranked.")
    return 0


def _cmd_rank(args: argparse.Namespace) -> int:
    from lender_engine.config import load_config
    from lender_engine.render import write_outputs
    from lender_engine.score import rank, score_account
    from lender_engine.store import AccountStore

    # Stored factors are the source of truth: re-scoring is free (no API
    # calls), so tuning the weights/floor and re-ranking is just an edit
    # of the config followed by this command.
    icp = load_config(args.config)
    with AccountStore(args.db) as store:
        accounts = store.all_accounts()
        if not accounts:
            print(f"No accounts stored in {args.db}. Run `python -m lender_engine run` first.")
            return 1
        accounts = rank([score_account(account, icp.scoring) for account in accounts])
        for account in accounts:
            store.upsert(account)
    for path in write_outputs(accounts, args.out, icp):
        print(f"Wrote {path}")
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    from lender_engine.brief import build_brief
    from lender_engine.config import load_config
    from lender_engine.llm import ClaudeClient
    from lender_engine.render import write_brief
    from lender_engine.score import rank
    from lender_engine.store import AccountStore

    store = AccountStore(args.db)
    if args.name is not None:
        account = store.get(args.name)
        if account is None:
            print(f"Account not found in {args.db}: {args.name}")
            return 1
    else:
        ranked = rank(store.all_accounts())
        if not ranked:
            print(f"No accounts stored in {args.db}. Run `python -m lender_engine run` first.")
            return 1
        account = ranked[0]
        print(f"No name given; briefing top-ranked account: {account.name}")

    icp = load_config(args.config)
    markdown = build_brief(account, icp, ClaudeClient())
    path = write_brief(markdown, account.name, args.out)
    print(f"Wrote {path}")
    return 0


def _cmd_seed(args: argparse.Namespace) -> int:
    # Only imports config (no enrich/llm/anthropic) so the offline seed
    # command runs without the anthropic dependency installed.
    from lender_engine.config import load_config, load_seeds

    icp = load_config(args.config)
    seeds = load_seeds(icp.seed_file)
    print(f"{len(seeds)} seed companies ({icp.name}):")
    for seed in seeds:
        reg = f" <{seed.registry.regulator} {seed.registry.as_of}>" if seed.registry else ""
        print(f"  - {seed.name} [{seed.segment}/{seed.sub_segment}] {seed.hq}{reg}")
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    from lender_engine.sources import build_seed_pool, inspect_registers

    if args.inspect:
        inspect_registers(args.manifest)
        return 0
    seeds, report = build_seed_pool(args.manifest, args.out)
    print(report)
    print(f"Wrote {len(seeds)} seeds to {args.out}")
    return 0


def _cmd_diagnose(args: argparse.Namespace) -> int:
    from lender_engine.config import load_config
    from lender_engine.diagnose import run_diagnostics, write_diagnostics

    icp = load_config(args.config)
    ranked = args.ranked or str(Path(args.out) / "ranked_accounts.json")
    if not Path(ranked).exists():
        print(f"No ranked output at {ranked}. Run `python -m lender_engine run` first.")
        return 1
    result = run_diagnostics(ranked, icp.scoring, top_k=args.top)
    for path in write_diagnostics(result, args.out):
        print(f"Wrote {path}")
    print(result["summary"])
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    handlers = {
        "run": _cmd_run,
        "rank": _cmd_rank,
        "brief": _cmd_brief,
        "seed": _cmd_seed,
        "sources": _cmd_sources,
        "diagnose": _cmd_diagnose,
    }
    sys.exit(handlers[args.command](args))
