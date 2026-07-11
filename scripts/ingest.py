"""Thin ingester entrypoint: `python scripts/ingest.py <X.Y.Z>`.

Fetches verbatim docs for one Rust release (via fetch_docs.py) and
updates the source/index.json catalog of snapshotted releases. This is
the single step the GHA ingest workflow calls -- no logic lives in the
YAML (see issue #1's "non-trivial logic lives in scripts/*.py" rule).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fetch_docs import fetch_release

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "source"
INDEX_JSON = SOURCE_DIR / "index.json"


def _update_catalog(release: str) -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    if INDEX_JSON.exists():
        catalog = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    else:
        catalog = {"releases": []}
    if release not in catalog["releases"]:
        catalog["releases"].append(release)
        catalog["releases"].sort(key=_version_key)
    INDEX_JSON.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    print(f"[catalog] {INDEX_JSON} -> {catalog['releases']}")


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: ingest.py <release, e.g. 1.94.1>")
    release = argv[1]
    fetch_release(release)
    _update_catalog(release)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
