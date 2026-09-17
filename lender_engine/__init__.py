"""Lender sourcing engine.

Sources lenders from public regulator registries, enriches each one from
public web data, scores it against a configurable ideal-customer profile,
and writes a ranked list where every signal carries its source and is
flagged sourced or inferred.
"""

__version__ = "0.2.0"
