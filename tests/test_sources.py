"""Register ingestion: manifest parsing, extract format, CSV/XLSX readers,
dedup across registers, full-pool vs enrichment-pool split. No network."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lender_engine.sources import (
    SourceError,
    build_seed_pool,
    load_manifest,
    normalize_name,
    parse_register,
)


class TestNormalize(unittest.TestCase):
    def test_suffixes_and_parentheticals_are_ignored(self):
        self.assertEqual(normalize_name("Tala Financing Philippines, Inc."), normalize_name("TALA FINANCING PHILIPPINES INC"))
        self.assertEqual(normalize_name("Netbank (A Rural Bank), Inc."), "netbank")
        self.assertNotEqual(normalize_name("Own Bank"), normalize_name("Owl Bank"))


class TestSources(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "raw").mkdir()
        (self.root / "extract").mkdir()

        # A hand-made extract (already normalized).
        with (self.root / "extract" / "digital.csv").open("w", newline="", encoding="utf-8") as h:
            w = csv.writer(h)
            w.writerow(["name", "registry_id", "hq", "extra"])
            w.writerow(["Alpha Digital Bank Inc.", "", "Manila, Philippines", "digital"])
            w.writerow(["Beta Bank Corporation", "", "", ""])

        # A raw CSV with a title row before the header and a company shared with the extract.
        with (self.root / "raw" / "sec.csv").open("w", newline="", encoding="utf-8") as h:
            w = csv.writer(h)
            w.writerow(["LIST OF LENDING COMPANIES WITH CA", "", ""])
            w.writerow(["No.", "Name of Company", "CA No."])
            w.writerow(["1", "Gamma Lending Corp.", "1001"])
            w.writerow(["2", "BETA BANK CORP.", "1002"])
            w.writerow(["", "", ""])
            w.writerow(["3", "Page 2 of 9", ""])

        # A raw XLSX.
        import openpyxl

        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(["Bank Name", "Head Office Address"])
        sheet.append(["Delta Thrift Bank, Inc.", "Cebu City"])
        sheet.append([None, None])
        book.save(self.root / "raw" / "bsp.xlsx")

        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "registers": [
                {"id": "digital", "source": "test extract", "regulator": "BSP", "url": "https://bsp.example",
                 "as_of": "2026-01-01", "file": "extract/digital.csv", "format": "extract",
                 "segment": "digital_bank", "include": True},
                {"id": "sec", "source": "test sec", "regulator": "SEC", "url": "https://sec.example",
                 "as_of": "2026-02-01", "file": "raw/sec.csv", "format": "csv",
                 "segment": "lending_company", "include": True,
                 "columns": {"name": "name of company", "registry_id": "ca no"},
                 "drop_regex": ["^page \\d+ of"]},
                {"id": "bsp", "source": "test bsp", "regulator": "BSP", "url": "https://bsp.example",
                 "as_of": "", "file": "raw/bsp.xlsx", "format": "xlsx",
                 "segment": "thrift_bank", "include": False,
                 "columns": {"name": "bank name", "hq": "address"}},
                {"id": "missing", "source": "not downloaded", "regulator": "SEC", "url": "https://sec.example",
                 "as_of": "", "file": "raw/nope.pdf", "format": "pdf", "segment": "financing_company", "include": True},
            ]
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_manifest_rejects_unknown_keys(self):
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({"registers": [{"id": "x", "source": "s", "regulator": "r", "url": "u",
                                                   "as_of": "", "file": "f", "format": "csv", "segment": "s",
                                                   "typo_key": 1}]}), encoding="utf-8")
        with self.assertRaises(SourceError):
            load_manifest(bad)

    def test_csv_register_finds_header_and_drops_junk(self):
        spec = [s for s in load_manifest(self.manifest) if s.id == "sec"][0]
        records = parse_register(spec, self.manifest)
        names = [r["name"] for r in records]
        self.assertEqual(names, ["Gamma Lending Corp.", "BETA BANK CORP."])
        self.assertEqual(records[0]["registry_id"], "1001")
        self.assertEqual(records[0]["hq"], "Philippines")  # hq_default

    def test_xlsx_register_reads_columns(self):
        spec = [s for s in load_manifest(self.manifest) if s.id == "bsp"][0]
        records = parse_register(spec, self.manifest)
        self.assertEqual(records, [{"name": "Delta Thrift Bank, Inc.", "registry_id": "", "hq": "Cebu City", "extra": ""}])

    def test_build_pool_dedups_and_splits(self):
        out = self.root / "seed.json"
        seeds, report = build_seed_pool(self.manifest, out)
        names = sorted(s.name for s in seeds)
        # Beta appears on two registers: kept once, from the first register that listed it.
        self.assertEqual(names, ["Alpha Digital Bank Inc.", "Beta Bank Corporation", "Gamma Lending Corp."])
        beta = [s for s in seeds if s.name.startswith("Beta")][0]
        self.assertEqual(beta.registry.regulator, "BSP")
        gamma = [s for s in seeds if s.name.startswith("Gamma")][0]
        self.assertEqual(gamma.registry.registry_id, "1001")
        self.assertEqual(gamma.registry.as_of, "2026-02-01")
        # Full pool has every row of every readable register, including the excluded one.
        with (self.root / "registry_pool_full.csv").open(encoding="utf-8") as h:
            rows = list(csv.DictReader(h))
        self.assertEqual(len(rows), 5)
        self.assertEqual({r["in_enrichment_pool"] for r in rows if r["segment"] == "thrift_bank"}, {"no"})
        self.assertIn("missing: SKIPPED", report)
        # The written seed file round-trips through the engine's loader.
        from lender_engine.config import load_seeds
        loaded = load_seeds(out)
        self.assertEqual(len(loaded), 3)
        self.assertEqual(loaded[0].registry.url, "https://bsp.example")


if __name__ == "__main__":
    unittest.main()
