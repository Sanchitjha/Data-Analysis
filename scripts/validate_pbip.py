"""Validate the generated Power BI project against Microsoft's published JSON schemas.

Usage: python scripts/validate_pbip.py          (needs internet: schemas are fetched from github.com/microsoft/json-schemas)
Checks .pbip, .pbism, .pbir and every report JSON file (report, pages, page, visuals).
"""
import functools
import json
import sys
from pathlib import Path

import requests
from jsonschema import Draft7Validator, RefResolver

ROOT = Path(__file__).resolve().parent.parent / "powerbi"
PREFIX = "https://developer.microsoft.com/json-schemas/"
RAW = "https://raw.githubusercontent.com/microsoft/json-schemas/main/"


@functools.lru_cache(None)
def fetch(uri: str) -> dict:
    uri = uri.split("#")[0]
    url = (RAW + uri[len(PREFIX):] if uri.startswith(PREFIX) else uri).replace("schema.embedded.json", "schema-embedded.json")  # typo in MS schemas
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=30)
            break
        except requests.exceptions.RequestException:
            if attempt == 3:
                raise
    r.raise_for_status()
    return r.json()


def errors(path: Path) -> list[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    schema = fetch(doc["$schema"])
    resolver = RefResolver(base_uri=doc["$schema"], referrer=schema, handlers={"https": fetch})
    return [f"{'/'.join(map(str, e.path))}: {e.message[:200]}" for e in Draft7Validator(schema, resolver=resolver).iter_errors(doc)]


def main() -> int:
    files = [ROOT / "Inventory.pbip", ROOT / "Inventory.SemanticModel" / "definition.pbism", ROOT / "Inventory.Report" / "definition.pbir",
             *sorted((ROOT / "Inventory.Report" / "definition").rglob("*.json"))]
    bad = 0
    for f in files:
        errs = errors(f)
        print(("OK   " if not errs else "FAIL ") + str(f.relative_to(ROOT)))
        for e in errs[:5]:
            print("     ", e)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
