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

No brief is shipped. The `brief` command was run twice on the top-ranked
account; both times the text carried claims labelled sourced without a URL
that could be checked against the stored evidence or the call's own search
results, and the second run ignored the prompt rule that every sourced
claim must carry one. A brief that cannot be checked sentence by sentence
is not shipped. The command stays; the prompt needs more work.
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
thrift, rural and cooperative). The raw files are not committed; the
extracts are. How each raw file was obtained is written in the manifest
notes, and two scripts reproduce the downloads:

- `scripts/fetch_bsp_directory.py` reads the BSP directory from the feed
  behind its public page and writes one CSV per bank type;
- `scripts/sec_tables_to_csv.py` converts the two SEC lists that are
  published as HTML tables (online lending platforms, revoked and
  suspended companies) from a capture of the rendered page.

The SEC lists of lending and financing companies with certificate of
authority are the 30 September 2023 PDFs, the most recent found on
sec.gov.ph; the pages the site links still show May 2020 lists.

The revoked and suspended list is a gate, not a prospect list. `sources`
matches every seed in the enrichment pool against it by normalized name and,
on a match, appends one sentence to the seed's notes naming the list and its
URL. It is a name match, not a certificate match, so the note says
"same-named entity" and leaves the judgement to the enrichment.

If a PDF resists the table parser, `sources --inspect` prints what
pdfplumber reads; adjust the column mapping or a line regex in the
manifest, or hand-build an extract in the normalized format.

## The run in this repository

The outputs committed here come from one run made on 17 and 18 September
2026: 174 seeds in the enrichment pool, 142 enriched and scored, 32 not
enriched. The run went through the pool in seed order (digital banks, thrift
banks, then online lending platform operators alphabetically) and was
stopped when the API credit balance ran out, so the 32 missing seeds are the
alphabetical tail of the operators, from Scoreone Financing to Yulon
Finance; they are listed in `data/not_enriched.csv` with their register ids.
The ranking is therefore a ranking of 142 lenders, and the diagnostics
describe those 142. Eleven of them score 0 because their closeability is
below the eligibility threshold: ten online lending platform operators
whose lifted revocation or cease-and-desist order the enrichment scored
low, and one thrift bank, Legazpi Savings Bank, because the BSP has
approved its merger into another bank. They are listed in the outputs, not
dropped.

## Scoring

Seven factors, each 0 to 1, each with a rationale and evidence items
flagged `sourced` (a public URL directly supports the claim) or `inferred`.

```
eligible    = closeability >= closeability_min        (else final = 0)
structural  = (acuity * roi_quant * whitespace) ^ (1/3)
operational = w1*winnability + w2*active_pain_timing + w3*reachability
final       = round(100 * structural * (floor + (1 - floor) * operational))
```

Closeability is a gate, not a factor: every lender in the pool holds a
licence, so a higher closeability does not make a better prospect, and a
lender below the threshold (revoked, suspended, under receivership) is not
sellable at all and scores 0. The threshold is `closeability_min` in the
config. The three structural factors multiply because each one can kill an
account on its own: no pain, no money in the pain, an installed incumbent.
The geometric mean keeps that gate while keeping the 0 to 100 scale readable.
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

python scripts/check_personal_data.py       # e-mails, phone numbers, personal profile URLs in committed files
python3 -m unittest discover tests          # 30 tests, no network
```

`run --skip-enriched` resumes an interrupted run without re-spending on
accounts already in the store. `run --only "Name"` (repeatable) processes
just the named seeds, `--skip "Name"` leaves them out. `--config` points the
engine at another profile; the same code, another market or another vendor.

Every API call appends its token counts and web search count to
`outputs/llm_usage.jsonl` (git-ignored), so the cost of a run can be read
back after the fact.

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

Known defect of this run: eleven accounts sit at score 0. Ten are online
lending platform operators scored low because the earlier wording of the
closeability rubric read a lifted revocation or cease-and-desist order,
noted on the current SEC register, as disqualifying. The eleventh, Legazpi
Savings Bank, is a thrift bank at 0 because the BSP has approved its merger
into another bank, which is a real gate, not a wording defect. The rubric
now says an order lowers closeability only while it is in force. The ten
operators were not re-enriched; doing so is about $4 of API spend that was
not spent, and their rank would change.

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
- The revoked-list cross-check is a name match. A same-named entity on the
  list may be a different company, and a revocation later lifted still
  matches. The enrichment prompt is asked to check the current status from
  public data.
- It is not a CRM and has no contact data.
- Its rankings have not been checked against any real pipeline.
