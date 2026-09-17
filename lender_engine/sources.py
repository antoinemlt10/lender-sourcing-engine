"""Build the seed pool from public regulator registers.

The pool is not typed in by hand. It is read from the lists a regulator
publishes (in the Philippines: the SEC lists of lending companies, financing
companies and online lending platforms; the BSP directory of banks), so
every seed carries the register it came from, the certificate or
registration number when the list has one, and the "as of" date printed on
the list.

How it works
------------
registries/manifest.json names each register: its source label, regulator,
public URL, as-of date, the local file it was downloaded to, its format
(pdf, xlsx, csv), the entity type it lists, how to find the columns, and
whether the register is in the enrichment pool or only in the full pool.

For each register this module:
  1. reads the file (pdfplumber for PDF tables, openpyxl for XLSX, csv for
     CSV), or reads a hand-made extract already in the normalized format;
  2. writes a normalized extract to registries/extract/<id>.csv with fixed
     columns (name, registry_id, hq, extra), so the parse is reviewable;
  3. merges every extract into one pool, deduplicated on a normalized name.

Two outputs:
  - data/seed_lenders.json: the seeds to enrich (registers with include=true);
  - data/registry_pool_full.csv: every row from every register, enriched or
    not, so the size of what was NOT enriched is visible.

If a PDF's layout defeats the table parser, run `sources --inspect` to see
what pdfplumber extracts, adjust the manifest (columns, header_contains,
line_regex), or hand-build registries/extract/<id>.csv with the normalized
columns and set "format": "extract" for that register.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lender_engine.models import Registry, SeedCompany

NORMALIZED_COLUMNS = ["name", "registry_id", "hq", "extra"]

# A register with this segment is not a prospect list but a gate: seeds whose
# normalized name also appears on it get a sentence appended to their notes.
GATE_SEGMENT = "revoked_or_suspended"

_CORP_SUFFIXES = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|opc|"
    r"a rural bank|a thrift bank|a savings bank)\b\.?",
    re.IGNORECASE,
)


class SourceError(Exception):
    """A register could not be read."""


@dataclass
class RegisterSpec:
    """One entry of registries/manifest.json."""

    id: str
    source: str
    regulator: str
    url: str
    as_of: str
    file: str
    format: str  # "pdf" | "xlsx" | "csv" | "extract"
    segment: str
    sub_segment: str = ""
    include: bool = True
    hq_default: str = "Philippines"
    # Column mapping for xlsx/csv/pdf tables: header substrings, case-insensitive.
    columns: dict[str, str] = field(default_factory=dict)
    # A header row is the first row containing this substring (default: the name column).
    header_contains: str = ""
    # PDF fallback when no table is detected: a regex with named groups
    # (?P<name>...) and optionally (?P<registry_id>...), applied per text line.
    line_regex: str = ""
    # Rows whose name matches any of these regexes are dropped (page headers, notes).
    drop_regex: list[str] = field(default_factory=list)
    # Free text for the human: where exactly the file was downloaded, what to check.
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegisterSpec:
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise SourceError(f"register {data.get('id')!r}: unknown keys {sorted(unknown)}")
        return cls(**data)


def normalize_name(name: str) -> str:
    """Key used to deduplicate across registers (a lender can be on two lists)."""
    text = name.lower()
    text = re.sub(r"\(.*?\)", " ", text)  # drop parentheticals such as (formerly ...)
    text = _CORP_SUFFIXES.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_manifest(path: str | Path) -> list[RegisterSpec]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("registers"), list):
        raise SourceError(f"{path}: expected an object with a 'registers' list")
    specs = [RegisterSpec.from_dict(item) for item in raw["registers"]]
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise SourceError(f"{path}: duplicate register ids")
    return specs


def _resolve(manifest_path: str | Path, file: str) -> Path:
    p = Path(file)
    return p if p.is_absolute() else (Path(manifest_path).resolve().parent / p).resolve()


# ---------------------------------------------------------------- readers


def _read_rows_xlsx(path: Path) -> list[list[str]]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise SourceError("openpyxl is required for .xlsx registers (pip install openpyxl)") from exc
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows: list[list[str]] = []
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            rows.append(["" if v is None else str(v).strip() for v in row])
    return rows


def _read_rows_csv(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [[c.strip() for c in row] for row in csv.reader(handle)]


def _read_rows_pdf(path: Path) -> tuple[list[list[str]], list[str]]:
    """Return (table rows across all pages, text lines across all pages)."""
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise SourceError("pdfplumber is required for .pdf registers (pip install pdfplumber)") from exc
    rows: list[list[str]] = []
    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    rows.append(["" if c is None else " ".join(str(c).split()) for c in row])
            text = page.extract_text() or ""
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return rows, lines


# ---------------------------------------------------------------- parsing


def _find_header(rows: list[list[str]], needle: str) -> int:
    needle = needle.lower()
    for i, row in enumerate(rows):
        if any(needle in cell.lower() for cell in row):
            return i
    raise SourceError(f"no header row contains {needle!r}")


def _column_index(header: list[str], needle: str) -> int:
    needle = needle.lower()
    for i, cell in enumerate(header):
        if needle in cell.lower():
            return i
    raise SourceError(f"no header column contains {needle!r} (header: {header})")


def _rows_to_records(rows: list[list[str]], spec: RegisterSpec) -> list[dict[str, str]]:
    name_needle = spec.columns.get("name", "name")
    header_idx = _find_header(rows, spec.header_contains or name_needle)
    header = rows[header_idx]
    idx = {"name": _column_index(header, name_needle)}
    for key in ("registry_id", "hq", "extra"):
        if key in spec.columns:
            try:
                idx[key] = _column_index(header, spec.columns[key])
            except SourceError:
                pass  # optional column absent on this list
    records: list[dict[str, str]] = []
    for row in rows[header_idx + 1 :]:
        if idx["name"] >= len(row):
            continue
        name = row[idx["name"]].strip()
        if not name:
            continue
        rec = {"name": name}
        for key, i in idx.items():
            if key != "name" and i < len(row):
                rec[key] = row[i].strip()
        records.append(rec)
    return records


def _lines_to_records(lines: list[str], spec: RegisterSpec) -> list[dict[str, str]]:
    if not spec.line_regex:
        raise SourceError(
            f"register {spec.id}: no table found in the PDF and no line_regex given; "
            "run `sources --inspect` and add a line_regex or a hand-made extract"
        )
    pattern = re.compile(spec.line_regex)
    records: list[dict[str, str]] = []
    for line in lines:
        m = pattern.search(line)
        if m and m.groupdict().get("name"):
            rec = {k: (v or "").strip() for k, v in m.groupdict().items()}
            records.append(rec)
    return records


def _clean(records: list[dict[str, str]], spec: RegisterSpec) -> list[dict[str, str]]:
    drops = [re.compile(p, re.IGNORECASE) for p in spec.drop_regex]
    out: list[dict[str, str]] = []
    for rec in records:
        name = " ".join(rec.get("name", "").split())
        if len(name) < 3 or any(d.search(name) for d in drops):
            continue
        # Skip rows that are just a number or a repeated header.
        if re.fullmatch(r"[\d\W]+", name) or name.lower() in ("name", "company name", "name of company"):
            continue
        out.append(
            {
                "name": name,
                "registry_id": " ".join(rec.get("registry_id", "").split()),
                "hq": rec.get("hq", "").strip() or spec.hq_default,
                "extra": " ".join(rec.get("extra", "").split()),
            }
        )
    return out


def parse_register(spec: RegisterSpec, manifest_path: str | Path) -> list[dict[str, str]]:
    """Parse one register into normalized records (not yet deduplicated)."""
    path = _resolve(manifest_path, spec.file)
    if not path.exists():
        raise SourceError(
            f"register {spec.id}: file not found: {path}. Download the list from "
            f"{spec.url} to that path, or set format 'extract' with a hand-made CSV."
        )
    if spec.format == "extract":
        rows = _read_rows_csv(path)
        header = [c.lower() for c in rows[0]] if rows else []
        if header[: len(NORMALIZED_COLUMNS)] != NORMALIZED_COLUMNS:
            raise SourceError(
                f"register {spec.id}: extract must start with columns {NORMALIZED_COLUMNS}, got {rows[0] if rows else []}"
            )
        records = [dict(zip(NORMALIZED_COLUMNS, row + [""] * 4)) for row in rows[1:] if row and row[0].strip()]
        return _clean(records, spec)
    if spec.format == "xlsx":
        return _clean(_rows_to_records(_read_rows_xlsx(path), spec), spec)
    if spec.format == "csv":
        return _clean(_rows_to_records(_read_rows_csv(path), spec), spec)
    if spec.format == "pdf":
        rows, lines = _read_rows_pdf(path)
        if rows and not spec.line_regex:
            try:
                return _clean(_rows_to_records(rows, spec), spec)
            except SourceError:
                pass  # fall through to the line regex if any
        return _clean(_lines_to_records(lines, spec), spec)
    raise SourceError(f"register {spec.id}: unknown format {spec.format!r}")


# ---------------------------------------------------------------- pool


def write_extract(records: list[dict[str, str]], extract_path: Path) -> None:
    extract_path.parent.mkdir(parents=True, exist_ok=True)
    with extract_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=NORMALIZED_COLUMNS)
        writer.writeheader()
        writer.writerows(records)


def build_seed_pool(manifest_path: str | Path, out_path: str | Path) -> tuple[list[SeedCompany], str]:
    """Parse every register in the manifest, write extracts, merge into a pool.

    Returns (seeds written to out_path, a human-readable report).
    """
    manifest_path = Path(manifest_path)
    specs = load_manifest(manifest_path)
    extract_dir = manifest_path.resolve().parent / "extract"
    full_rows: list[dict[str, str]] = []
    seeds: dict[str, SeedCompany] = {}
    gate_rows: list[tuple[RegisterSpec, dict[str, str]]] = []
    report_lines: list[str] = []
    for spec in specs:
        if not _resolve(manifest_path, spec.file).exists():
            report_lines.append(
                f"{spec.id}: SKIPPED, file not found ({spec.file}); download it from {spec.url}"
            )
            continue
        records = parse_register(spec, manifest_path)
        if spec.format != "extract":
            write_extract(records, extract_dir / f"{spec.id}.csv")
        if spec.segment == GATE_SEGMENT:
            gate_rows.extend((spec, rec) for rec in records)
        included = 0
        for rec in records:
            key = normalize_name(rec["name"])
            full_rows.append(
                {
                    "name": rec["name"],
                    "segment": spec.segment,
                    "sub_segment": spec.sub_segment,
                    "regulator": spec.regulator,
                    "register": spec.source,
                    "registry_id": rec["registry_id"],
                    "as_of": spec.as_of,
                    "url": spec.url,
                    "in_enrichment_pool": "yes" if spec.include else "no",
                }
            )
            if not spec.include or key in seeds:
                continue
            included += 1
            seeds[key] = SeedCompany(
                name=rec["name"],
                segment=spec.segment,
                sub_segment=spec.sub_segment,
                hq=rec["hq"],
                notes=rec["extra"],
                registry=Registry(
                    source=spec.source,
                    regulator=spec.regulator,
                    url=spec.url,
                    as_of=spec.as_of,
                    registry_id=rec["registry_id"],
                ),
            )
        report_lines.append(
            f"{spec.id}: {len(records)} rows read ({spec.regulator}, as of {spec.as_of or 'unknown'}); "
            f"{included} added to the enrichment pool" if spec.include else
            f"{spec.id}: {len(records)} rows read ({spec.regulator}, as of {spec.as_of or 'unknown'}); "
            "kept in the full pool only (include=false)"
        )

    annotated = annotate_gate_matches(seeds, gate_rows)
    if gate_rows:
        report_lines.append(
            f"Gate cross-check: {len(annotated)} seed(s) share a normalized name with a "
            f"{GATE_SEGMENT} register row: {', '.join(annotated) or 'none'}"
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([s.to_dict() for s in seeds.values()], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    full_path = out_path.parent / "registry_pool_full.csv"
    with full_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(full_rows[0].keys()) if full_rows else ["name"])
        writer.writeheader()
        writer.writerows(full_rows)
    report_lines.append(
        f"Full pool: {len(full_rows)} register rows -> {full_path.name}; "
        f"enrichment pool: {len(seeds)} unique lenders -> {out_path.name}"
    )
    return list(seeds.values()), "\n".join(report_lines)


def annotate_gate_matches(
    seeds: dict[str, SeedCompany], gate_rows: list[tuple[RegisterSpec, dict[str, str]]]
) -> list[str]:
    """Cross-check the enrichment pool against gate registers (segment
    revoked_or_suspended, for example the SEC list of revoked and suspended
    companies).

    The match is on the same normalized name the pool is deduplicated on, so
    it is a name match, not a certificate match: a same-named entity may be a
    different company, which is why the note says "same-named" and leaves the
    judgement to the enrichment and the reader. Every matching seed gets one
    sentence appended to its notes, naming the register and its URL and
    saying whether the list prints a date. Returns the names annotated.
    """
    by_key: dict[str, list[RegisterSpec]] = {}
    for spec, rec in gate_rows:
        by_key.setdefault(normalize_name(rec["name"]), [])
        if spec not in by_key[normalize_name(rec["name"])]:
            by_key[normalize_name(rec["name"])].append(spec)
    annotated: list[str] = []
    for key, seed in seeds.items():
        for spec in by_key.get(key, []):
            dated = f"that list is as of {spec.as_of}" if spec.as_of else "that list prints no date"
            sentence = (
                f"Cross-check: a same-named entity appears on the {spec.source} "
                f"({spec.url}); {dated}."
            )
            seed.notes = f"{seed.notes} {sentence}".strip() if seed.notes else sentence
            annotated.append(seed.name)
    return annotated


def inspect_registers(manifest_path: str | Path, rows_to_show: int = 8) -> None:
    """Print what the readers see in each file, to map columns before parsing."""
    manifest_path = Path(manifest_path)
    for spec in load_manifest(manifest_path):
        path = _resolve(manifest_path, spec.file)
        print(f"== {spec.id} [{spec.format}] {path}")
        if not path.exists():
            print("   (file missing)")
            continue
        try:
            if spec.format == "pdf":
                rows, lines = _read_rows_pdf(path)
                print(f"   {len(rows)} table rows, {len(lines)} text lines")
                for row in rows[:rows_to_show]:
                    print("   T", row)
                for line in lines[:rows_to_show]:
                    print("   L", line)
            elif spec.format == "xlsx":
                for row in _read_rows_xlsx(path)[:rows_to_show]:
                    print("   ", row)
            else:
                for row in _read_rows_csv(path)[:rows_to_show]:
                    print("   ", row)
        except SourceError as exc:
            print(f"   ERROR: {exc}")
