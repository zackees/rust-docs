"""Build site/<release>/index.db from source/<release>/ + _cache/<release>/chunks/.

Schema per issue #1 -- one DB per release, identical shape, no `release`
column filter (partitioning is by which DB file you open, not a WHERE
clause):

  documents      -- path/upstream_url/rendered_url/sha256/size_bytes
  chunks         -- external-content source for search_porter
  search_porter  -- FTS5, porter unicode61, external-content over chunks
  document_text  -- full untruncated verbatim text per doc_id (the FK
                    retrieval path -- an agent gets a whole article with
                    no external download/extraction tool)
  fulltext       -- FTS5 external-content over document_text, for ranked
                    in-document snippet windows

Pitfalls carried over from FastLED/datasheets / memex IMPLEMENT.md:
  - `PRAGMA page_size = 32768` MUST precede the first CREATE.
  - External-content FTS5 rowids must line up with the source table's
    rowid so `INSERT INTO search_*(search_*) VALUES('rebuild')` hits the
    right rows.
  - End with PRAGMA optimize + VACUUM so pages pack contiguously for
    HTTP range reads.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "source"
CACHE_DIR = REPO_ROOT / "_cache"
SITE_DIR = REPO_ROOT / "site"

# Hard size budget per DB. Our corpus is a few dozen small verbatim
# .md/.rs files per release (tens of KB each) -- this should land in the
# low single-digit MB, nowhere near datasheets' 40 MB PDF-driven budget.
MAX_MB = 20


def _canonical_kind(anchor: str, rel_within_anchor: str) -> str:
    if anchor == "rustc-dev-guide":
        return "dev-guide"
    if anchor == "sccache":
        return "reference-impl"
    if rel_within_anchor.startswith("src/doc/"):
        return "book"
    if anchor == "rust":
        return "rustc-source"
    if anchor == "cargo":
        return "cargo-source"
    return "source"


def _repo_for_anchor(anchor: str, anchors: dict) -> str:
    return anchors.get(anchor, {}).get("repo", anchor)


def _rendered_url(anchor: str, rel_within_anchor: str) -> str | None:
    if anchor == "cargo" and rel_within_anchor.startswith("src/doc/src/reference/"):
        slug = rel_within_anchor.removeprefix("src/doc/src/reference/").removesuffix(".md")
        return f"https://doc.rust-lang.org/cargo/reference/{slug}.html"
    if anchor == "rust" and rel_within_anchor.startswith("src/doc/rustc/src/"):
        slug = rel_within_anchor.removeprefix("src/doc/rustc/src/").removesuffix(".md")
        return f"https://doc.rust-lang.org/rustc/{slug}.html"
    if anchor == "rustc-dev-guide" and rel_within_anchor.startswith("src/"):
        slug = rel_within_anchor.removeprefix("src/").removesuffix(".md")
        return f"https://rustc-dev-guide.rust-lang.org/{slug}.html"
    return None


def _build_schema(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE documents (
            doc_id         INTEGER PRIMARY KEY,
            release        TEXT NOT NULL,
            repo           TEXT NOT NULL,
            canonical_kind TEXT NOT NULL,
            path           TEXT NOT NULL,
            upstream_url   TEXT NOT NULL,
            rendered_url   TEXT,
            sha256         TEXT NOT NULL,
            size_bytes     INTEGER NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX idx_documents_repo ON documents(repo)")
    cur.execute("CREATE INDEX idx_documents_kind ON documents(canonical_kind)")

    cur.execute(
        """
        CREATE TABLE chunks (
            doc_id   INTEGER NOT NULL,
            heading  TEXT,
            text     TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        )
        """
    )
    cur.execute("CREATE INDEX idx_chunks_doc ON chunks(doc_id)")

    cur.execute(
        """
        CREATE VIRTUAL TABLE search_porter USING fts5(
            text,
            content='chunks', content_rowid='rowid',
            tokenize='porter unicode61 remove_diacritics 1',
            columnsize=0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE document_text (
            doc_id  INTEGER PRIMARY KEY REFERENCES documents(doc_id),
            text    TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE VIRTUAL TABLE fulltext USING fts5(
            text,
            content='document_text', content_rowid='doc_id',
            tokenize='porter unicode61 remove_diacritics 1'
        )
        """
    )


def build_release(release: str) -> Path:
    release_source = SOURCE_DIR / release
    manifest_path = release_source / "manifest.json"
    chunks_dir = CACHE_DIR / release / "chunks"
    if not manifest_path.exists():
        raise SystemExit(f"missing {manifest_path}; run ingest.py {release} first")
    if not chunks_dir.exists():
        raise SystemExit(f"missing {chunks_dir}; run chunk_docs.py {release} first")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    anchors = manifest["anchors"]

    db_dir = SITE_DIR / release
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "index.db"
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA page_size = 32768")
    cur.execute("PRAGMA journal_mode = DELETE")
    _build_schema(cur)

    files = manifest["files"]
    doc_rows = []
    for entry in files:
        # path is "<release>/<anchor>/<rel_within_anchor>"
        parts = entry["path"].split("/", 2)
        anchor = parts[1]
        rel_within_anchor = parts[2]
        repo = _repo_for_anchor(anchor, anchors)
        kind = _canonical_kind(anchor, rel_within_anchor)
        rendered_url = _rendered_url(anchor, rel_within_anchor)
        doc_rows.append((
            release, repo, kind, entry["path"], entry["url"], rendered_url,
            entry["sha256"], entry["size_bytes"],
        ))
    cur.executemany(
        """
        INSERT INTO documents (
            release, repo, canonical_kind, path, upstream_url, rendered_url,
            sha256, size_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        doc_rows,
    )

    # doc_id assignment follows INSERT order (INTEGER PRIMARY KEY, no
    # explicit rowid given) -- files[i] -> doc_id i+1.
    total_chunks = 0
    next_rowid = 1
    for idx, entry in enumerate(files):
        doc_id = idx + 1
        chunk_file = chunks_dir / f"{idx:04d}.json"
        record = json.loads(chunk_file.read_text(encoding="utf-8"))
        assert record["path"] == entry["path"], (record["path"], entry["path"])

        chunk_rows = []
        full_text_parts = []
        for c in record["chunks"]:
            chunk_rows.append((next_rowid, doc_id, c["heading"], c["text"]))
            full_text_parts.append(c["text"])
            next_rowid += 1
        if chunk_rows:
            cur.executemany(
                "INSERT INTO chunks(rowid, doc_id, heading, text) VALUES (?, ?, ?, ?)",
                chunk_rows,
            )
            total_chunks += len(chunk_rows)

        full_text = SOURCE_DIR.joinpath(entry["path"]).read_text(
            encoding="utf-8", errors="replace"
        )
        cur.execute(
            "INSERT INTO document_text(doc_id, text) VALUES (?, ?)",
            (doc_id, full_text),
        )

    print(f"[build] {release}: {len(files)} documents, {total_chunks} chunks")

    cur.execute("INSERT INTO search_porter(search_porter) VALUES('rebuild')")
    cur.execute("INSERT INTO fulltext(fulltext) VALUES ('rebuild')")
    conn.commit()

    cur.execute("PRAGMA optimize")
    conn.commit()
    conn.isolation_level = None
    cur.execute("VACUUM")
    conn.isolation_level = ""
    conn.close()

    size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"[build] wrote {db_path} ({size_mb:.2f} MB)")
    if size_mb > MAX_MB:
        raise SystemExit(
            f"! {db_path} is {size_mb:.2f} MB, exceeds {MAX_MB} MB budget"
        )
    return db_path


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] != "--release":
        raise SystemExit("usage: build_index.py --release <X, e.g. 1.94.1>")
    build_release(argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
