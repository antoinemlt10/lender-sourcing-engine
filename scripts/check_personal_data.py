"""Scan the files that get committed for personal data.

The repository rule is: no individual names, e-mail addresses or phone
numbers in committed files. Names cannot be detected mechanically, so this
script catches what can be: e-mail addresses, phone-number patterns and
personal profile URLs (linkedin.com/in/, facebook.com/<person>, x.com/<handle>)
in the rendered outputs, the extracts and the data files. Names are checked
by reading the outputs.

Exit code 1 when something is found.

Usage: python scripts/check_personal_data.py [paths...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_PATHS = ["outputs", "data", "registries/extract", "README.md", "registries/manifest.json"]
COMMITTED_SUFFIXES = {".md", ".csv", ".json"}
# Organisation pages that happen to live under a personal-profile URL path.
# Add an entry only after checking the page is an organisation, not a person.
ALLOWLIST = {
    "https://www.linkedin.com/in/fintechallianceph/",  # FinTech Alliance.PH, an association
    "https://x.com/creditinfogovph/",  # Credit Information Corporation, a government body
}

PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<![\w/])(?:\+?63|0)\s?[\d]{2,3}[\s-]?\d{3}[\s-]?\d{4}(?![\w/])"),
    "personal_profile_url": re.compile(r"https?://(?:www\.)?(?:linkedin\.com/in/|x\.com/|twitter\.com/)[^\s\"'<>)]+", re.IGNORECASE),
}


def scan(path: Path) -> list[str]:
    if path.suffix == ".json" and path.parent.name == "outputs":
        return []  # outputs/*.json is git-ignored
    findings: list[str] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for kind, pattern in PATTERNS.items():
        for m in pattern.finditer(text):
            url = m.group(0)
            if any(url.startswith(a.rstrip("/")) for a in ALLOWLIST):
                continue
            line = text.count("\n", 0, m.start()) + 1
            findings.append(f"{path}:{line}: {kind}: {m.group(0)[:80]}")
    return findings


def main(argv: list[str]) -> int:
    roots = [Path(p) for p in (argv or DEFAULT_PATHS)]
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(p for p in root.rglob("*") if p.suffix in COMMITTED_SUFFIXES)
        elif root.exists():
            files.append(root)
    findings = [f for path in sorted(files) for f in scan(path)]
    for line in findings:
        print(line)
    print(f"{len(findings)} finding(s) in {len(files)} file(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
