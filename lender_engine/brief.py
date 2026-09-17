"""Build the deep account brief for a single account."""

import json

from lender_engine.config import ICPConfig
from lender_engine.llm import ClaudeClient
from lender_engine.models import Account


def build_brief(account: Account, icp: ICPConfig, client: ClaudeClient) -> str:
    """Generate a Markdown deep brief for one account.

    Uses prompts/deep_brief.md with web search enabled so the brief can
    cite fresh public sources. The brief covers: company snapshot, the
    specific likely pain, mapping to the vendor's product, key roles, a
    short outreach opener, and a POC hypothesis with a kill criterion.
    """
    variables = {
        "account_name": account.name,
        "account_json": json.dumps(account.to_dict(), indent=2),
        "icp_name": icp.name,
        "vendor_name": icp.vendor["name"],
        "vendor_description": icp.vendor["description"],
        "wedge": icp.wedge,
    }
    return client.complete(
        "deep_brief",
        variables,
        web_search=True,
        max_tokens=8192,
    )
