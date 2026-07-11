"""Relevance regression test: every canned query in scripts/queries_data.py
must return its target doc(s) among the top hits, for every built release
DB under site/<release>/index.db. Also exercises the document_text full-
retrieval path once, per issue #1's acceptance criteria.

Usage: python tests/test_queries.py [release ...]
Defaults to every release with a built site/<release>/index.db.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = REPO_ROOT / "site"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from queries_data import QUERIES  # noqa: E402

TOP_N = 10


def _run_query(conn: sqlite3.Connection, match: str) -> list[str]:
    cur = conn.execute(
        """
        SELECT documents.path
        FROM search_porter
        JOIN chunks ON chunks.rowid = search_porter.rowid
        JOIN documents ON documents.doc_id = chunks.doc_id
        WHERE search_porter MATCH ?
        ORDER BY bm25(search_porter)
        LIMIT ?
        """,
        (match, TOP_N),
    )
    return [row[0] for row in cur.fetchall()]


def _check_full_text_retrieval(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT doc_id, length(text) FROM document_text "
        "WHERE doc_id = (SELECT doc_id FROM documents WHERE path LIKE '%fingerprint/mod.rs' LIMIT 1)"
    ).fetchone()
    return row is not None and row[1] > 1000


def test_release(release: str) -> bool:
    db_path = SITE_DIR / release / "index.db"
    if not db_path.exists():
        raise SystemExit(f"missing {db_path}; run build_index.py --release {release} first")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    passed = 0
    failed = []
    for q in QUERIES:
        hits = _run_query(conn, q["match"])
        ok = any(any(t in h for t in q["targets"]) for h in hits)
        if ok:
            passed += 1
        else:
            failed.append(q["question"])

    ft_ok = _check_full_text_retrieval(conn)
    conn.close()

    print(f"[{release}] {passed}/{len(QUERIES)} queries hit their target doc; "
          f"full-text retrieval: {'ok' if ft_ok else 'FAILED'}")
    for q in failed:
        print(f"  MISS: {q}")
    return not failed and ft_ok


def main(argv: list[str]) -> int:
    releases = argv[1:]
    if not releases:
        if not SITE_DIR.exists():
            raise SystemExit(f"no {SITE_DIR}; build at least one release first")
        releases = sorted(p.name for p in SITE_DIR.iterdir()
                           if p.is_dir() and (p / "index.db").exists())
    if not releases:
        raise SystemExit("no built release DBs found under site/")

    ok = True
    for release in releases:
        ok = test_release(release) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
