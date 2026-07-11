"""Confirm the local/CLI cross-version ATTACH + UNION ALL diff path from
docs/cross-version-diff.md still works: two release DBs opened via
ATTACH, searched together, each hit correctly tagged by release.

Requires at least two built site/<release>/index.db. Skips (exit 0) if
fewer than two are available -- this is a capability check, not a
per-release content test (see tests/test_queries.py for that).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"


def main() -> int:
    releases = sorted(p.name for p in SITE_DIR.iterdir()
                       if p.is_dir() and (p / "index.db").exists()) if SITE_DIR.exists() else []
    if len(releases) < 2:
        print(f"[skip] need >=2 built release DBs, found {releases}")
        return 0

    a, b = releases[0], releases[1]
    conn = sqlite3.connect(":memory:")
    conn.execute(f"ATTACH '{SITE_DIR / a / 'index.db'}' AS a")
    conn.execute(f"ATTACH '{SITE_DIR / b / 'index.db'}' AS b")

    rows = conn.execute(
        """
        SELECT 'a' AS release, d.path FROM a.chunks c
        JOIN a.search_porter ON search_porter.rowid = c.rowid
        JOIN a.documents d ON d.doc_id = c.doc_id
        WHERE search_porter MATCH 'fingerprint AND hash'
        UNION ALL
        SELECT 'b', d.path FROM b.chunks c
        JOIN b.search_porter ON search_porter.rowid = c.rowid
        JOIN b.documents d ON d.doc_id = c.doc_id
        WHERE search_porter MATCH 'fingerprint AND hash'
        """
    ).fetchall()
    conn.close()

    has_a = any(r[0] == "a" for r in rows)
    has_b = any(r[0] == "b" for r in rows)
    ok = has_a and has_b
    print(f"[{'OK' if ok else 'FAIL'}] cross-version ATTACH ({a} vs {b}): "
          f"{len(rows)} rows, a={has_a} b={has_b}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
