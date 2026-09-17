<!-- string.Template prompt: placeholders are dollar-prefixed, a literal dollar must be doubled. No web search: work only from the signals below. Required variables: company_name, vendor_name, vendor_description, wedge, extracted_json -->

# Task

Write the angle for a first conversation between $vendor_name and
**$company_name**: the specific, small, bounded pilot that $vendor_name should
propose, grounded in this lender's own situation.

# The vendor

$vendor_description

# Wedge (the ICP owner's hypothesis)

$wedge

# Extracted signals for this lender

```json
$extracted_json
```

# Instructions

- Write 2-4 sentences of plain prose, no headings or bullets.
- Anchor the angle in THIS lender's specific situation from the signals
  above: its products, application process, required documents, turnaround,
  recent moves or hiring. Not a generic pitch.
- Name the product line that fits (document capture and risk scoring,
  application flow, underwriting decision) only where the signals justify it.
- Frame it as a hypothesis to test in a bounded pilot with a clear success
  metric (for example days-to-decision, share of applications decided
  without a manual step, document rejection rate), not a promise.
- Stay honest: use only what the signals support; where the signals were
  marked "inferred", hedge accordingly ("likely", "if, as it appears, ...").

Respond with the 2-4 sentence angle only, no preamble, no JSON.
