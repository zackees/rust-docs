"""Path 1 (default, zero-dep): download a release's index.db, then query
it with stdlib sqlite3. Runs the canned queries from queries.md and
demonstrates the document_text full-retrieval path -- an agent gets a
whole article by doc_id with no external download/extraction tool.

Usage:
    python examples/query.py 1.94.1
    python examples/query.py 1.94.1 --base-url https://zackees.github.io/rust-docs
    python examples/query.py 1.94.1 --db-path ./site/1.94.1/index.db  # skip download
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from queries_data import QUERIES  # noqa: E402

DEFAULT_BASE_URL = "https://zackees.github.io/rust-docs"


def _download(url: str, dest: Path) -> None:
    print(f"[get] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "rust-docs-query-example/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    print(f"[ok ] {dest} ({dest.stat().st_size} bytes)")


def open_db(release: str, base_url: str, db_path: Path | None) -> sqlite3.Connection:
    if db_path is None:
        db_path = Path(f"_downloaded_{release}_index.db")
        if not db_path.exists():
            _download(f"{base_url}/{release}/index.db", db_path)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def run_query(conn: sqlite3.Connection, match: str, limit: int = 5) -> list[tuple]:
    cur = conn.execute(
        """
        SELECT documents.path, chunks.heading, documents.doc_id,
               snippet(search_porter, 0, '[', ']', ' ... ', 16) AS snip
        FROM search_porter
        JOIN chunks ON chunks.rowid = search_porter.rowid
        JOIN documents ON documents.doc_id = chunks.doc_id
        WHERE search_porter MATCH ?
        ORDER BY bm25(search_porter)
        LIMIT ?
        """,
        (match, limit),
    )
    return cur.fetchall()


def fetch_full_text(conn: sqlite3.Connection, doc_id: int) -> str:
    row = conn.execute(
        "SELECT text FROM document_text WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    return row[0] if row else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("release", help="e.g. 1.94.1")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--db-path", type=Path, default=None,
                     help="use an already-local index.db instead of downloading")
    args = ap.parse_args()

    conn = open_db(args.release, args.base_url, args.db_path)

    print(f"\n=== canned queries against {args.release} ===")
    for q in QUERIES[:3]:
        print(f"\nQ: {q['question']}")
        print(f"   MATCH: {q['match']}")
        for path, heading, doc_id, snip in run_query(conn, q["match"], limit=3):
            print(f"   - {path}  [{heading}]  (doc_id={doc_id})")
            print(f"     {snip}")

    print("\n=== full-document retrieval by doc_id (no external tool) ===")
    first_hit = run_query(conn, QUERIES[0]["match"], limit=1)
    if first_hit:
        doc_id = first_hit[0][2]
        text = fetch_full_text(conn, doc_id)
        print(f"doc_id={doc_id}: retrieved {len(text)} chars of untruncated verbatim text")
        print(text[:300] + ("..." if len(text) > 300 else ""))

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
