# Lender sourcing engine

A command-line tool that builds a pool of lenders from public regulator
registers, enriches each one from public web data, scores it against a
configurable ideal-customer profile, ranks the pool, and then checks its own
ranking for the ways a ranking goes wrong: ties at the cut, factors that do
not discriminate, evidence that is mostly inferred, an order that changes
when one weight moves by 0.1.

Start here:

- `outputs/ranked_accounts.md`: the ranked list, once a run has been made
- `outputs/diagnostics.md`: what the ranking is worth, in numbers
- `configs/kita_philippines_icp.json`: the profile it was run against, every
  rubric marked as a hypothesis
- `registries/manifest.json`: which public lists the pool came from, as of
  which date

Origin: the scoring engine was first written as a work sample for another
company's go-to-market role. For this repository the sourcing layer was
replaced by regulator registers, the prompts were made vendor-neutral (the
vendor is described in the config, not in the code), and the diagnostics
module was added. Nothing in the code names a company.

## What the pool is made of

The pool is not typed in. `registries/manifest.json` lists public registers
and, for each, its regulator, public URL, the date printed on the list, the
local file, the format and how to read its columns. `python -m lender_engine
sources` parses them and writes:

- `data/seed_lenders.json`: the lenders to enrich, each carrying the
  register it came from, its certificate or registration number when the
  list has one, and the list's as-of date;
- `data/registry_pool_full.csv`: every row of every register, enriched or
  not, so the size of what was left out is visible;
- `registries/extract/<id>.csv`: the normalized parse of each register, for
  review.

For the Philippines the manifest names the SEC lists of lending companies,
financing companies and recorded online lending platforms, the SEC list of
revoked and suspended companies, and the BSP directory of banks (digital,
thrift, rural and cooperative). The raw files are not committed; download
them on the day you build the pool and record their dates. The repository
ships with a six-row starter extract (the digital banks, from a 2022 press
report) so that the commands run end to end before any register has been
downloaded; the manifest says to replace it.

If a PDF resists the table parser, `sources --inspect` prints what
pdfplumber reads; adjust the column mapping or a line regex in the
manifest, or hand-build an extract in the normalized format.

## Scoring

Seven factors, each 0 to 1, each with a rationale and evidence items
flagged `sourced` (a public URL directly supports the claim) or `inferred`.

```
structural  = (acuity * roi_quant * whitespace * closeability) ^ (1/4)
operational = w1*winnability + w2*active_pain_timing + w3*reachability
final       = round(100 * structural * (floor + (1 - floor) * operational))
```

Structural factors multiply because each one can kill an account on its
own: no pain, no money in the pain, an installed incumbent, no licence. The
geometric mean keeps that gate while keeping the 0 to 100 scale readable.
Operational factors add because they trade off. The floor keeps a
structurally strong account visible when nothing is happening there this
quarter. Weights and floor live in the config; re-ranking after a change is
`python -m lender_engine rank`, no API calls.

The factor names are generic. What each one means for a given vendor is
written in the config's rubrics. For the Kita config:

| Factor | Reads as |
|---|---|
| acuity | document-heavy, manual underwriting of thin-file borrowers |
| roi_quant | origination volume and the cost of slow or wrong decisions |
| whitespace | no installed loan origination or decisioning vendor visible |
| closeability | licensed and in good standing with BSP or SEC |
| winnability | size, ownership, procurement culture |
| active_pain_timing | signals from the past 12 months |
| reachability | associations, events, shared investors, at role level |

## Diagnostics

`python -m lender_engine diagnose` reads the ranked output and writes
`outputs/diagnostics.md`:

- distinct scores, largest tie groups, and whether the shortlist cut falls
  inside a tie (with the accounts on each side of it);
- mean, spread and number of distinct values per factor, flagging factors
  that move no one;
- the share of evidence with a public URL, overall, per factor and per
  entity type;
- top-k stability: the order recomputed under a 0.10 shift of each weight
  and of the floor, with the share of the shortlist that survives and the
  Spearman correlation of the full order.

The check exists because a ranking built from an LLM rubric can produce
many equal scores, and a shortlist cut inside a tie group is a coin toss
that looks like a decision. On the engine's earlier run (87 accounts, other
domain), the diagnostics found 41 distinct scores, a four-way tie at rank 8
to 11, and a rank-15 account that leaves the shortlist under four of the
eight perturbations. That run is not in this repository; the numbers are
quoted to say what the check catches.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY

python -m lender_engine sources --inspect   # what the parser sees in each register file
python -m lender_engine sources             # build the pool (no API calls)
python -m lender_engine seed                # list the pool
python -m lender_engine run --limit 10      # enrich, score, rank (2 API calls per lender, web search on)
python -m lender_engine rank                # re-score and re-render after a config change (no API calls)
python -m lender_engine diagnose            # distribution checks on outputs/ranked_accounts.json
python -m lender_engine brief "Name"        # one-page brief on one account (web search on)

python3 -m unittest discover tests          # 25 tests, no network
```

`run --skip-enriched` resumes an interrupted run without re-spending on
accounts already in the store. `--config` points the engine at another
profile; the same code, another market or another vendor.

## Rules the enrichment follows

- Public web data only. No scraped private sources.
- No individual names, emails or phone numbers. Personas are roles.
- Every evidence item cites a URL or is flagged inferred with an empty URL.
- No invented internal metrics: loan book, NPL ratio, volumes, revenue.
- Name collisions are flagged in the snapshot rather than resolved by guess.

## What is fact and what is hypothesis

Fact: the register rows (name, regulator, certificate number, list date) and
every evidence item flagged sourced, each with its URL. The vendor
description in the config quotes public sources dated in the file.

Hypothesis: every rubric, the weights, the floor, the choice of which
registers go into the enrichment pool, and the empty incumbents list. They
are the config author's reading of who buys this product, written from
public material only. The right next step is to put them next to the
vendor's real pipeline: if the top ten do not convert to first meetings at a
visibly higher rate than ranks twenty to thirty, the rubrics are wrong and
should be edited, which is a config change.

## What this does not do

- It does not know Philippine lending law or credit risk in emerging
  markets. It reads registers and public pages.
- It does not verify licence status against the SEC revoked list by a hard
  join yet; the prompt asks for it from public data. A join on the extract
  is a small next step.
- It is not a CRM and has no contact data.
- Its rankings have not been checked against any real pipeline.
