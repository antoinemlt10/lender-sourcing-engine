"""End-to-end pipeline: seed -> enrich -> score -> persist -> render."""

from lender_engine.config import ICPConfig, apply_closeability_override, load_seeds
from lender_engine.enrich import Enricher, PublicWebEnricher
from lender_engine.models import Account
from lender_engine.render import write_outputs
from lender_engine.score import rank, score_account
from lender_engine.store import AccountStore


class PipelineError(Exception):
    """The pipeline could not produce any output (e.g. every company failed)."""


def run_pipeline(
    icp: ICPConfig,
    limit: int | None = None,
    db_path: str = "lenders.db",
    out_dir: str = "outputs",
    enricher: Enricher | None = None,
    skip_enriched: bool = False,
    skip_names: list[str] | None = None,
    only_names: list[str] | None = None,
) -> list[Account]:
    """Run the full pipeline and return the ranked accounts.

    Resilient by design: a single company failing to enrich is logged and
    skipped rather than killing the whole run. If EVERY company fails, we
    leave any previous good outputs untouched and raise PipelineError.
    With only_names, just those seeds are processed (a targeted pilot).
    With skip_enriched=True, seeds already present in the store are not
    re-enriched (no API spend); this makes interrupted runs resumable.
    The rendered outputs always reflect the whole store, not just this run.
    """
    if limit is not None and limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")

    seeds = load_seeds(icp.seed_file)
    if only_names:
        # Mirror of --skip: keep only the named seeds (for a targeted pilot).
        wanted = set(only_names)
        seeds = [seed for seed in seeds if seed.name in wanted]
        missing = sorted(wanted - {seed.name for seed in seeds})
        if missing:
            print(f"WARNING: --only names not in the seed pool: {', '.join(missing)}")
        print(f"Restricting to {len(seeds)} named seed(s).")
    if skip_names:
        skips = set(skip_names)
        seeds = [seed for seed in seeds if seed.name not in skips]
        print(f"Skipping by name: {', '.join(sorted(skips))}.")
    if limit is not None:
        seeds = seeds[:limit]

    accounts: list[Account] = []
    failures: list[tuple[str, str]] = []
    with AccountStore(db_path) as store:
        if skip_enriched:
            already = {account.name for account in store.all_accounts()}
            skipped = [seed for seed in seeds if seed.name in already]
            seeds = [seed for seed in seeds if seed.name not in already]
            if skipped:
                print(f"Skipping {len(skipped)} already-enriched accounts.")

        if not seeds:
            print("Nothing to enrich (limit=0, empty seed pool, or all already "
                  "enriched); no outputs written.")
            return []

        total = len(seeds)
        if enricher is None:
            enricher = PublicWebEnricher()

        for i, seed in enumerate(seeds, start=1):
            print(f"[{i}/{total}] Enriching {seed.name}...")
            try:
                account = enricher.enrich(seed, icp)
                account = apply_closeability_override(account, icp)
                account = score_account(account, icp.scoring)
                store.upsert(account)
                accounts.append(account)
            except Exception as exc:  # noqa: BLE001 - one failure must not kill the run
                message = f"{type(exc).__name__}: {exc}"
                failures.append((seed.name, message))
                print(f"  WARNING: skipping {seed.name} ({message})")

        if not accounts:
            print(
                f"ERROR: all {total} companies failed to enrich; leaving previous "
                f"outputs in {out_dir} untouched."
            )
            raise PipelineError(f"all {total} companies failed to enrich")

        ranked = rank(store.all_accounts())

    for path in write_outputs(ranked, out_dir, icp):
        print(f"Wrote {path}")
    if failures:
        print(f"{len(failures)} of {total} companies failed to enrich (see warnings above).")
    return ranked
