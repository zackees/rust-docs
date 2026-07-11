"""Byte-range servability check -- same gate as the verify job in
.github/workflows/build-site.yml, runnable locally against any already
deployed site (or a local static server that supports Range).

Usage:
    python tests/test_deploy_verification.py [base_url]

Defaults to the live site. Exits non-zero if any release's index.db
fails to answer 206 Partial Content with a valid Content-Range and the
SQLite magic bytes.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://zackees.github.io/rust-docs"


def _fetch_meta(base_url: str) -> dict:
    import json
    req = urllib.request.Request(f"{base_url}/_meta.json",
                                  headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _range_probe(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(
        url, headers={"Range": "bytes=0-4095", "Accept-Encoding": "identity"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            content_range = resp.headers.get("Content-Range", "")
            body = resp.read(4096)
    except urllib.error.HTTPError as e:
        status = e.code
        content_range = e.headers.get("Content-Range", "") if e.headers else ""
        body = b""

    if status != 206:
        return False, f"expected 206, got {status}"
    if not content_range.startswith("bytes 0-4095/"):
        return False, f"bad Content-Range: {content_range!r}"
    if body[:4] != b"SQLi":
        return False, f"first 4 bytes are not 'SQLi': {body[:4]!r}"
    return True, "ok"


def main(argv: list[str]) -> int:
    base_url = argv[1].rstrip("/") if len(argv) > 1 else DEFAULT_BASE_URL
    meta = _fetch_meta(base_url)
    urls = list(meta["version_db_url"].values())
    if not urls:
        raise SystemExit("no releases in _meta.json version_db_url")

    fail = False
    for url in urls:
        ok, detail = _range_probe(url)
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {url}: {detail}")
        fail = fail or not ok

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
