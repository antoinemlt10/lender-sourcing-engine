"""Download the BSP Directory of Banks and Non-Bank Financial Institutions.

The public page (https://www.bsp.gov.ph/SitePages/FinancialStability/DirBanksFIList.aspx)
renders a table from a SharePoint list named "Institutions" through the site's
REST API. This script reads that list, page by page, and writes one CSV per
bank type into registries/raw/ (git-ignored):

  bsp_digital_banks.csv   InstitutionTypeID 14 (Digital Banks)
  bsp_thrift_banks.csv    InstitutionTypeID 10 (Thrift Banks)
  bsp_rural_banks.csv     InstitutionTypeID 11 (Rural and Cooperative Banks)

Only institution-level fields are kept: name, BSP institution id, type ids,
short name, address, number of offices, status code, website, and the row's
modified timestamp. The list also carries the name, e-mail, phone and fax of
each institution's head; those fields are not requested and never written.

The type codes come from the "Financial Institution" list on the same site
and are written to registries/raw/bsp_institution_types.csv for reference.

Usage: python scripts/fetch_bsp_directory.py
"""

from __future__ import annotations

import csv
import json
import time
import urllib.request
from pathlib import Path

BASE = "https://www.bsp.gov.ph/_api/web/lists/getbytitle('{list}')/items"
FIELDS = [
    "InstitutionID", "Title", "ShortBankName", "InstitutionTypeID",
    "InstitutionTypeID2", "InstitutionTypeID3", "Address", "NumOffice",
    "Status", "Website", "Modified",
]
TYPES = {"14": "bsp_digital_banks.csv", "10": "bsp_thrift_banks.csv", "11": "bsp_rural_banks.csv"}
RAW = Path(__file__).resolve().parent.parent / "registries" / "raw"

# The site's edge blocks browser user agents on the API path; a plain client
# user agent is served. No cookies or credentials are involved.
HEADERS = {"User-Agent": "Python-urllib/3", "Accept": "application/json;odata=nometadata"}


def get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
        return json.load(resp)


def fetch_all(list_name: str, select: str) -> list[dict]:
    url = BASE.format(list=list_name) + f"?$select={select}&$top=500"
    rows: list[dict] = []
    while url:
        data = get(url)
        rows.extend(data["value"])
        url = data.get("odata.nextLink")
        time.sleep(1)
    return rows


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    types = fetch_all("Financial%20Institution", "Id,Code,Title")
    with (RAW / "bsp_institution_types.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["code", "title"])
        for t in sorted(types, key=lambda t: float(t["Code"] or 0)):
            writer.writerow([int(float(t["Code"])), t["Title"].strip()])

    rows = fetch_all("Institutions", ",".join(FIELDS))
    print(f"{len(rows)} rows in the BSP Institutions list")
    header = ["institutionid", "bank", "short_name", "type_id", "type_id2", "type_id3",
              "address", "num_offices", "status", "website", "modified"]
    for type_id, filename in TYPES.items():
        subset = [r for r in rows if str(r["InstitutionTypeID"]) == type_id]
        subset.sort(key=lambda r: r["Title"].lower())
        with (RAW / filename).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for r in subset:
                writer.writerow([
                    r["InstitutionID"], " ".join((r["Title"] or "").split()), r["ShortBankName"] or "",
                    r["InstitutionTypeID"], r["InstitutionTypeID2"], r["InstitutionTypeID3"],
                    " ".join((r["Address"] or "").split()), r["NumOffice"] or "", r["Status"] or "",
                    r["Website"] or "", r["Modified"],
                ])
        print(f"  {filename}: {len(subset)} rows")


if __name__ == "__main__":
    main()
