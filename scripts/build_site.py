"""Assemble the published site/ tree: static UI + memex vendor bundle +
every already-built site/<release>/index.db + the agent-facing catalog.

Upstream steps (in order):
    1. scripts/fetch_memex.py          -> site-src/vendor/
    2. scripts/ingest.py <release>     -> source/<release>/
    3. scripts/chunk_docs.py <release> -> _cache/<release>/chunks/
    4. scripts/build_index.py --release <release> -> site/<release>/index.db
    5. (this script) assembles site/, writes site/_meta.json + .nojekyll

Idempotent for the static parts (site-src/* copied verbatim); does NOT
touch already-built site/<release>/index.db files -- those are produced
by build_index.py and are the thing this script indexes into _meta.json.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE_SRC = REPO_ROOT / "site-src"
SITE_OUT = REPO_ROOT / "site"
SOURCE_DIR = REPO_ROOT / "source"
BUILDERS_DIR = REPO_ROOT / "builders"

SCHEMA = {
    "documents": ["doc_id", "release", "repo", "canonical_kind", "path",
                  "upstream_url", "rendered_url", "sha256", "size_bytes"],
    "chunks": ["doc_id", "heading", "text"],
    "search_porter": "FTS5(text) external-content over chunks, "
                      "tokenize='porter unicode61 remove_diacritics 1'",
    "document_text": ["doc_id", "text"],
    "fulltext": "FTS5(text) external-content over document_text, "
                "tokenize='porter unicode61 remove_diacritics 1'",
}

EXAMPLE_QUERIES = [
    {
        "question": "What inputs go into a unit fingerprint?",
        "match": "fingerprint AND (input OR hash OR dirty OR fresh)",
    },
    {
        "question": "Where does Cargo persist freshness state on disk (.fingerprint/)?",
        "match": '"fingerprint" AND (directory OR json OR "on disk" OR store)',
    },
    {
        "question": "What lives in target/, deps/, incremental/; rlib/rmeta linking layout?",
        "match": "target AND (deps OR incremental OR rlib OR rmeta)",
    },
]


def _commit_sha() -> str:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        )
        return out.decode("ascii").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _memex_sha() -> str:
    f = BUILDERS_DIR / "MEMEX_SHA"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return "unknown"


def _copy_static() -> None:
    SITE_OUT.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.html", "*.js", "*.css"):
        for src in SITE_SRC.glob(pattern):
            shutil.copy2(src, SITE_OUT / src.name)
    vendor_src = SITE_SRC / "vendor"
    if vendor_src.exists():
        shutil.copytree(vendor_src, SITE_OUT / "vendor", dirs_exist_ok=True)
    else:
        print(f"[warn] {vendor_src} missing -- run scripts/fetch_memex.py first")


def _releases() -> list[str]:
    index_json = SOURCE_DIR / "index.json"
    if not index_json.exists():
        return []
    return json.loads(index_json.read_text(encoding="utf-8"))["releases"]


def _copy_manifests(releases: list[str]) -> None:
    for release in releases:
        src = SOURCE_DIR / release / "manifest.json"
        if not src.exists():
            continue
        dst_dir = SITE_OUT / release
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst_dir / "manifest.json")


def _db_entry(release: str, base_url: str) -> dict | None:
    db_path = SITE_OUT / release / "index.db"
    if not db_path.exists():
        print(f"[skip] {db_path} not built yet")
        return None
    import hashlib
    sha256 = hashlib.sha256(db_path.read_bytes()).hexdigest()
    return {
        "release": release,
        "db_url": f"{base_url}/{release}/index.db",
        "manifest_url": f"{base_url}/{release}/manifest.json",
        "size_bytes": db_path.stat().st_size,
        "sha256": sha256,
    }


def _write_meta(releases: list[str], commit: str, memex_sha: str, base_url: str) -> Path:
    version_map = {}
    catalog = []
    for release in releases:
        entry = _db_entry(release, base_url)
        if entry is None:
            continue
        version_map[release] = entry["db_url"]
        catalog.append(entry)

    meta = {
        "commit": commit,
        "memex_sha": memex_sha,
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "releases": catalog,
        "version_db_url": version_map,
        "schema": SCHEMA,
        "example_queries": EXAMPLE_QUERIES,
        "guidance": (
            "Version is a required selector -- open one release's index.db by URL "
            "from version_db_url; there is no unscoped/default cross-version query. "
            "Prefer online HTTP-range querying; downloading a whole per-version DB "
            "is fine too, each is only a few MB. A search_porter MATCH hit returns "
            "a doc_id; SELECT text FROM document_text WHERE doc_id=? retrieves the "
            "full untruncated article with no external download/extraction tool."
        ),
    }
    dst = SITE_OUT / "_meta.json"
    dst.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[meta] {dst}: {len(catalog)} release(s)")
    return dst


def _write_nojekyll() -> None:
    (SITE_OUT / ".nojekyll").write_bytes(b"")


def main() -> int:
    if not SITE_SRC.exists():
        raise SystemExit(f"missing {SITE_SRC}")

    base_url = os.environ.get("RUST_DOCS_BASE_URL", "https://zackees.github.io/rust-docs").rstrip("/")
    releases = _releases()

    _copy_static()
    _copy_manifests(releases)

    commit = _commit_sha()
    memex_sha = _memex_sha()
    _write_meta(releases, commit, memex_sha, base_url)
    _write_nojekyll()

    print(f"\nSite assembled at {SITE_OUT}")
    print(f"  commit    = {commit}")
    print(f"  memex_sha = {memex_sha}")
    print(f"  releases  = {releases}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
