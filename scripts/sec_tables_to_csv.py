r"""Convert the SEC HTML tables captured from sec.gov.ph into CSV registers.

The SEC publishes two of the registers used here as HTML tables on its
website rather than as files:

  - List of Recorded Online Lending Platforms
    https://www.sec.gov.ph/lending-companies-and-financing-companies-2/list-of-recorded-online-lending-platforms/
  - List of Revoked and Suspended Lending Companies
    https://www.sec.gov.ph/lending-companies-and-financing-companies-2/list-of-revoked-and-suspended-lending-companies/

sec.gov.ph sits behind a bot challenge that blocks scripted downloads, so
the tables were read from the rendered page in a normal Chrome session
with this snippet, run in the page console, and the JSON was saved to
registries/raw/ (git-ignored) without any edit:

    [...document.querySelectorAll('table')].map(t =>
      [...t.rows].map(r => [...r.cells].map(c => c.textContent.replace(/\s+/g, ' ').trim())))

For the revoked page each table is stored with the heading that precedes
it, because the page holds six lists (revoked lending CA, revoked
financing CA, suspended lending CA, revoked primary registration,
revoked partnerships, cease-and-desist orders).

This script writes:

  registries/raw/sec_olp.csv                one row per company
  registries/raw/sec_revoked_suspended.csv  one row per company, with the
                                            list it came from and its date

Usage: python scripts/sec_tables_to_csv.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "registries" / "raw"


def write_olp() -> None:
    rows = json.loads((RAW / "sec_olp_table.json").read_text(encoding="utf-8"))
    header = ["no", "company name", "sec number", "online lending platform",
              "date of form 1 submission", "date of letter confirmation", "remarks"]
    with (RAW / "sec_olp.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows[1:]:
            writer.writerow((row + [""] * len(header))[: len(header)])
    print(f"sec_olp.csv: {len(rows) - 1} rows")


def write_revoked() -> None:
    tables = json.loads((RAW / "sec_revoked_tables.json").read_text(encoding="utf-8"))
    header = ["name", "list", "date", "sec registration no", "ca no", "online lending platform", "status"]
    count = 0
    with (RAW / "sec_revoked_suspended.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for table in tables:
            heading = table["heading"]
            rows = table["rows"]
            first = [c.lower() for c in rows[0]]
            if "company name" in first:  # the cease-and-desist table has more columns
                for row in rows[1:]:
                    row = row + [""] * 6
                    writer.writerow([row[1], heading, "", row[2], row[3], row[4], row[5]])
                    count += 1
            else:  # name, date of revocation
                for row in rows[1:]:
                    row = row + [""] * 2
                    writer.writerow([row[0], heading, row[1], "", "", "", ""])
                    count += 1
    print(f"sec_revoked_suspended.csv: {count} rows from {len(tables)} tables")


if __name__ == "__main__":
    write_olp()
    write_revoked()
