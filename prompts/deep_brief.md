<!-- string.Template prompt: placeholders are dollar-prefixed, a literal dollar must be doubled. Web search enabled. Required variables: account_name, account_json, icp_name, vendor_name, vendor_description, wedge -->

# Task

Write a one-page account brief on **$account_name** for $vendor_name, in
Markdown, for a founder who has four minutes before a call.

# The vendor

$vendor_description

# ICP: $icp_name

$wedge

# What the engine already found

```json
$account_json
```

# Instructions

Use web search sparingly to refresh or confirm the signals above; cite every
new fact with its URL. Keep the same honesty rules as the enrichment: public
data only, no invented numbers, sourced vs inferred stated explicitly, and
two hard rules. No individual's name anywhere in the brief, including inside
quotes: refer to people by role ("the bank's president said", "a LANDBANK
executive stated"). A cited URL must be the lender's own site, a regulator
page, an official app store listing, a recognised news outlet, or an
association or investor page; never a mirror site, content farm, unrelated
domain reproducing the lender's text, or loan-review aggregator as the only
support for a fact. If that is all you find, say the fact is inferred and why.

Structure, in this order, each section short:

1. **Snapshot**: who they are, what they lend, to whom, how a borrower applies.
2. **The specific pain**: where documents and manual underwriting cost them
   time or money, with the evidence and its confidence.
3. **Fit with $vendor_name's product**: which product line, why, and what
   would NOT fit.
4. **Roles**: champion and economic buyer at role level, and who might block.
5. **First conversation**: a three-sentence opener grounded in their own
   public statements, and two questions to ask.
6. **Pilot hypothesis**: scope, success metric, and the kill criterion that
   would tell $vendor_name to stop.
7. **What we do not know**: the two or three facts that would change this
   assessment most, and where to get them.

Respond with the Markdown brief only.
