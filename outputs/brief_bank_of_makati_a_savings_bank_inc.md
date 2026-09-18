# Bank of Makati (A Savings Bank), Inc. — Account Brief

## 1. Snapshot
Bank of Makati is a BSP-licensed thrift bank founded in 1956, with assets worth P60.83 billion as of end-March, placing eighth in the sector, and around 100 branches. It lends across motorcycle, personal/payday, housing, auto, and MSME loans, historically anchored in motorcycle financing. Consumer borrowers apply with ID, proof of income and supporting financial documents — a personal loan application usually requires valid identification, proof of income, and supporting financial documents, with additional paperwork needed depending on the borrower's profile — while business borrowers submit corporate documents, financial statements, and authorized signatory details. Salary/payday loans are unsecured: "This salary loan asks for no collateral nor guarantor to get you approved."

## 2. The specific pain
Three converging, sourced signals point to a document- and model-quality gap:
- **Manual, judgment-heavy underwriting**: the bank's own site flags variable paperwork requirements depending on borrower profile, consistent with a human-review-driven process rather than automated decisioning (sourced, above).
- **Credit-model refinement underway**: the bank's president stated the lender is refining its credit-scoring models as it works to improve its bad loan ratio (sourced).
- **Fraud tooling explicitly a gap**: the president said fraud management systems available in the local market remain costly for smaller lenders and might not fully suit the operational needs of thrift banks, "the offerings are still too expensive and the features do not necessarily match what we need" (sourced) — a direct, on-record admission of an unmet buying need adjacent to document risk scoring.

## 3. Fit with Kita's product
Best fit: **Kita Capture + AI Underwriter** on the personal/payday salary-loan and MSME lines, where document intake (ID, payslip, business permit, bank statements) already drives approval and the bank has openly said commercial fraud tools don't fit its size or budget — a gap Document Risk Score is built for. **Intelligent LOS** is a plausible fit given the bank is actively selecting a new loan system, but timing risk is high if a vendor is already shortlisted. **Not a fit**: housing and auto loans, which are collateral-driven, and universal-bank-style bureau-based decisioning, which is not this bank's core model.

## 4. Roles
- **Champion**: Head of Credit / Chief Risk Officer for consumer and MSME lending — owns document review quality, turnaround, and the bad-loan-ratio work already underway.
- **Economic buyer**: President — the on-record voice for the core-banking/loan-system migration, digital platform launch, and IT investment decisions, and a Chamber of Thrift Banks board officer.
- **Possible blocker**: whoever owns the Finacle core-banking and new loan-system vendor relationship, since procurement may already be committed for the loan-system leg of the migration.

## 5. First conversation
Opener: "You've said the bank is refining its credit-scoring models to improve the bad-loan ratio while migrating to a new loan system before January's rollout — and that off-the-shelf fraud tools are too costly and don't fit a thrift bank's needs. That's precisely the gap between manual document review and a new LOS that Kita sits in. We'd like to show you a document-risk layer that plugs into that gap before the new system locks in vendors." Questions: (1) "Has the new loan system's underwriting/decisioning module already been selected, or is that still open?" (2) "On the personal loan and MSME lines, what share of applications currently need a human to chase or re-verify a document?"

## 6. Pilot hypothesis
**Scope**: Run Kita Capture + AI Underwriter in shadow mode alongside manual review on new personal/payday-loan applications at a subset of branches, fixed volume (e.g., a few hundred applications). **Success metric**: days-to-decision versus current manual turnaround, and % of applications clearing without a human document-review step. **Kill criterion**: if the loan-system vendor decision is already finalized with no room for an underwriting-layer integration, or if the bank's fraud/document risk concern turns out to be primarily a cost objection rather than a capability gap — stop and revisit after the January core-system go-live.

## 7. What we don't know
- Whether the **new loan system's underwriting module has already been vendor-selected** — this determines if the window is truly open (ask the champion directly).
- **Ticket size and volume** on the personal/payday and MSME lines — needed to size ROI; not published, would require a data-sharing conversation.
- Whether the **fraud-tooling gap** the president described refers to AML/transaction fraud or document/application fraud — changes whether Document Risk Score is the right wedge (clarify in first call).