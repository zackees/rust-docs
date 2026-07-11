"""Fetch pinned memex WASM bundle into site-src/vendor/.

Reads the target commit SHA from builders/MEMEX_SHA and downloads the
prebuilt SQLite-over-HTTP client (memex.js + webpack chunks +
sqlite3.wasm) from that pinned commit. Ported from FastLED/datasheets'
tools/fetch_memex.py — memex is the pinned client-side query engine, not
a crawler we invoke.

Idempotent: files already present with a plausible signature are skipped.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHA_FILE = REPO_ROOT / "builders" / "MEMEX_SHA"
VENDOR_DIR = REPO_ROOT / "site-src" / "vendor"

FILES = [
    "memex.js",
    "sqlite3.wasm",
    "memex-141.js",
    "memex-272.js",
    "memex-676.js",
    "memex-901.js",
]

JS_PREFIXES = (b"/**", b"import", b"(function", b"/*!", b"\"use strict\"",
               b"'use strict'", b"export", b"var ", b"const ", b"let ",
               b"!function", b"(()=>", b"(self", b"(globalThis", b"//")
WASM_MAGIC = b"\x00asm"


def _read_sha() -> str:
    if not SHA_FILE.exists():
        raise SystemExit(f"missing {SHA_FILE}")
    sha = SHA_FILE.read_text(encoding="utf-8").strip()
    if not sha:
        raise SystemExit(f"empty SHA in {SHA_FILE}")
    return sha


def _looks_valid(path: Path) -> bool:
    if not path.exists():
        return False
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(256)
    if path.suffix == ".wasm":
        return size > 1024 and head.startswith(WASM_MAGIC)
    if path.suffix == ".js":
        stripped = head.lstrip()
        low = stripped.lower()
        if low.startswith(b"<!doctype") or low.startswith(b"<html") or low.startswith(b"<?xml"):
            return False
        if any(stripped.startswith(p) for p in JS_PREFIXES):
            return True
        if path.name == "memex.js" and size <= 1024:
            return False
        return stripped[:1] in (b"(", b"!", b"[", b"{")
    return True


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "rust-docs-fetch-memex/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"URL error fetching {url}: {e}") from e
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def main() -> int:
    sha = _read_sha()
    base = f"https://raw.githubusercontent.com/zackees/memex/{sha}/dist/wasm/"
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    fetched = 0
    skipped = 0
    for name in FILES:
        dest = VENDOR_DIR / name
        if _looks_valid(dest):
            print(f"[skip] {name} already present ({dest.stat().st_size} bytes)")
            skipped += 1
            continue
        url = base + name
        print(f"[get ] {url}")
        _download(url, dest)
        if not _looks_valid(dest):
            size = dest.stat().st_size if dest.exists() else 0
            with dest.open("rb") as fh:
                head = fh.read(64)
            raise SystemExit(
                f"downloaded {name} failed validation: size={size} head={head!r}"
            )
        print(f"[ok  ] {name} -> {dest} ({dest.stat().st_size} bytes)")
        fetched += 1

    print(f"\nmemex SHA: {sha}")
    print(f"fetched {fetched}, skipped {skipped}, total {len(FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
