# Distribution diagnostics

Source: `outputs/ranked_accounts.json` · weights {'winnability': 0.35, 'active_pain_timing': 0.35, 'reachability': 0.3} · floor 0.4

142 accounts, 39 distinct scores (133 accounts share a score with at least one other). The top-15 cut does not fall inside a tie. Low-spread factors: none. Sourced evidence: 76% of items have a public URL. Stability: a 0.10 shift in one weight keeps at least 100% of the top-15 (worst: winnability +0.10); full-order Spearman >= 0.995.

## Ties

- Accounts: 142 · distinct scores: 39 (27%)
- Accounts sharing a score: 133

| Score | Count | Accounts |
|------:|------:|----------|
| 0 | 11 | Cash Mart Asia Lending Inc., Cashbee Lending Services Inc., Elending Lending Inc, Fast Coin Lending Corp, Gofcash Lending Corporation operating under the name of Gogo Cash, GoFcash, GoFcash VIP and GoFcash Loan (formerly: Fcash Global Lending Inc), Hi-Fin Lending, Inc., Kayamo Atlas Lending Corp, Legazpi Savings Bank, Inc., Lucky Shell Fintech Lending, Inc., Makati Loan, Inc. doing business under the name and style of Peso Cash Loan, Microdot Lending Corporation |
| 28 | 10 | AstraFund Lending Corp. Doing Business under the names and styles of Surelo and Cashinin (formerly: FLASH CASH 101 LENDING CORP. Doing business under FLASH CASH LENDING), Dolphin Lending Investor, Inc., Equicom Savings Bank, Inc., FlexiPeso Lending Inc. doing business under the name/s and style/s of QuickPuhunan, CashSagip, LendWais, LuckyPera, WorthyFund and CashTugon, ISLA Bank (A Thrift Bank), Inc., Idirect Finance Company Inc, LENDORA LENDING CORP. doing business under the names and styles of Lendra and Finplo (formerly Treasure Bowl Fintech Lending Corp.), Myloan Lending Investors Inc, Nfinit Lending Corporation, Queen City Development Bank, Inc. or Queenbank, A Thrift Bank |
| 25 | 8 | AETHERIUM LENDING, INC. doing business under the name of BilisCash, PesoKey, SurePeso (formerly Codeblock Lending Inc.), First Circle Growth Finance Corp, Ifun Lending Corp. Doing Business Under The Name And Style Of “Madaloan”, Leaflending Inc. doing business under the name/s and style/s of CredoPera, Loanova and OnePeso, Makiling Development Bank Corporation, Pampanga Development Bank, Perajet Lending Corporation, University Savings Bank, Inc. |
| 24 | 7 | Asiasource Financial Inc, First Digital Finance Corporation, Lf Lending Services Corporation, Online Loans Pilipinas Financing Inc., Overseas Filipino Bank, Inc., A Digital Bank of LANDBANK, Paloo Financing, Inc., Peso Redee Financing Co. Inc. |
| 37 | 6 | Advance Tech Lending Inc., Ceimmarj Financing Incorporated, Copperstone Lending Inc., Empire Peak Lending Investors Inc, Leapgen Lending Inc., UNObank, Inc. |
| 34 | 6 | GoTyme Bank Corporation, Hupan Lending Technology Inc, Inclusive Credit Lending Inc., Link Credit Lending Investors Inc, MCP Finance Inc (formerly “Transnational Financial Services, Inc.”), Mabilis Cash Financing Corp |

### Top-15 boundary

No tie at the boundary.

## Factor spread

| Factor | Mean | SD | Min | Max | Distinct | Flag |
|---|---:|---:|---:|---:|---:|---|
| acuity | 0.536 | 0.161 | 0.12 | 0.9 | 18 |  |
| roi_quant | 0.435 | 0.176 | 0.15 | 0.9 | 17 |  |
| whitespace | 0.508 | 0.234 | 0.05 | 0.85 | 20 |  |
| closeability | 0.818 | 0.189 | 0.1 | 1.0 | 19 |  |
| winnability | 0.398 | 0.132 | 0.08 | 0.75 | 18 |  |
| active_pain_timing | 0.356 | 0.186 | 0.1 | 0.85 | 18 |  |
| reachability | 0.308 | 0.142 | 0.15 | 0.75 | 13 |  |

## Sourced vs inferred

- Evidence items: 2282 · sourced overall: 76% · accounts with no evidence at all: 0

| Factor | Sourced | Items |
|---|---:|---:|
| acuity | 84% | 498 |
| roi_quant | 71% | 341 |
| whitespace | 63% | 304 |
| closeability | 87% | 377 |
| winnability | 79% | 289 |
| active_pain_timing | 75% | 267 |
| reachability | 62% | 206 |

| Entity type | Sourced | Items |
|---|---:|---:|
| thrift_bank | 77% | 700 |
| lending_company | 74% | 1458 |
| digital_bank | 96% | 124 |

## Top-15 stability under ±0.10 shifts

| Perturbation | Top-k kept | Jaccard | Spearman | Dropped | Entered |
|---|---:|---:|---:|---|---|
| winnability +0.10 | 15/15 | 1.0 | 0.998 |  |  |
| winnability -0.10 | 15/15 | 1.0 | 0.998 |  |  |
| active_pain_timing +0.10 | 15/15 | 1.0 | 0.998 |  |  |
| active_pain_timing -0.10 | 15/15 | 1.0 | 0.998 |  |  |
| reachability +0.10 | 15/15 | 1.0 | 0.999 |  |  |
| reachability -0.10 | 15/15 | 1.0 | 0.998 |  |  |
| floor +0.10 | 15/15 | 1.0 | 0.995 |  |  |
| floor -0.10 | 15/15 | 1.0 | 0.997 |  |  |
