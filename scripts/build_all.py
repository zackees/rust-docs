"""Orchestrate a full multi-version build: chunk + index every release in
source/index.json, but only recompile a release's index.db when its
source/<release>/ content actually changed.

Content hash = sha256 of the sorted "path:sha256" pairs from that
release's manifest.json -- i.e. exactly the set of bytes ingest.py
fetched, independent of anything else in the repo. If a previous build
output is available (`--prev-site <dir>`, e.g. a checkout of the
published `site` branch), a release whose hash matches its prior
`.content_hash` is restored verbatim (index.db + manifest.json copied,
not recompiled); a changed or new release is chunked + rebuilt.

This is the "recompile a version's DB only when its source/<version>/
folder hash changes" rule from issue #1 -- the catalog (_meta.json,
source/index.json) always regenerates via build_site.py regardless.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import chunk_docs
import build_index

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "source"
SITE_DIR = REPO_ROOT / "site"


def content_hash(release: str) -> str:
    manifest = json.loads((SOURCE_DIR / release / "manifest.json").read_text(encoding="utf-8"))
    pairs = sorted(f"{f['path']}:{f['sha256']}" for f in manifest["files"])
    return hashlib.sha256("\n".join(pairs).encode("utf-8")).hexdigest()


def _restore(release: str, prev_site: Path) -> bool:
    prev_db = prev_site / release / "index.db"
    prev_manifest = prev_site / release / "manifest.json"
    prev_hash_file = prev_site / release / ".content_hash"
    if not (prev_db.exists() and prev_hash_file.exists()):
        return False
    if prev_hash_file.read_text(encoding="utf-8").strip() != content_hash(release):
        return False
    dst = SITE_DIR / release
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(prev_db, dst / "index.db")
    if prev_manifest.exists():
        shutil.copy2(prev_manifest, dst / "manifest.json")
    (dst / ".content_hash").write_text(content_hash(release) + "\n", encoding="utf-8")
    return True


def build_release_if_changed(release: str, prev_site: Path | None) -> str:
    if prev_site is not None and _restore(release, prev_site):
        print(f"[skip] {release}: content hash unchanged, restored from previous build")
        return "restored"

    print(f"[build] {release}: content hash changed (or no prior build) -- recompiling")
    chunk_docs.chunk_release(release)
    build_index.build_release(release)
    dst = SITE_DIR / release
    (dst / ".content_hash").write_text(content_hash(release) + "\n", encoding="utf-8")
    return "built"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev-site", type=Path, default=None,
                     help="checkout of the previously published site/ tree, for cache restoration")
    args = ap.parse_args(argv[1:])

    index_json = SOURCE_DIR / "index.json"
    if not index_json.exists():
        raise SystemExit(f"missing {index_json}")
    releases = json.loads(index_json.read_text(encoding="utf-8"))["releases"]

    summary = {}
    for release in releases:
        summary[release] = build_release_if_changed(release, args.prev_site)

    print("\n[build_all] summary:")
    for release, status in summary.items():
        print(f"  {release}: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
