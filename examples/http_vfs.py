"""Path 2 (spike): query a release's index.db over HTTP range requests
without downloading the whole file, using APSW's custom VFS support
(stdlib sqlite3 cannot register a VFS).

Status: SPIKE, per issue #1 -- confirm a live range query works, record
pages fetched per query, and note the same gzip-defeats-Range pitfall
as the browser path (memex IMPLEMENT.md pitfall #1): GitHub Pages must
receive `Accept-Encoding: identity` or it serves the gzipped blob and
SQLite reads the gzip magic as page 0.

Requires: pip install apsw

Usage:
    python examples/http_vfs.py 1.94.1
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

try:
    import apsw
except ImportError:
    apsw = None

DEFAULT_BASE_URL = "https://zackees.github.io/rust-docs"
PAGE_SIZE = 32768  # must match build_index.py's PRAGMA page_size


class HttpRangeFile:
    """Minimal APSW VFSFile backed by HTTP Range GETs, page-aligned to
    PAGE_SIZE. Tracks request count for the per-query page-fetch report.
    """

    def __init__(self, url: str):
        self.url = url
        self.request_count = 0
        self.bytes_fetched = 0
        req = urllib.request.Request(url, method="HEAD",
                                      headers={"Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.size = int(resp.headers["Content-Length"])

    def xRead(self, amount: int, offset: int) -> bytes:
        self.request_count += 1
        self.bytes_fetched += amount
        req = urllib.request.Request(
            self.url,
            headers={
                "Range": f"bytes={offset}-{offset + amount - 1}",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 206:
                raise IOError(
                    f"expected 206 Partial Content, got {resp.status} -- "
                    f"is the server gzipping despite Accept-Encoding: identity? "
                    f"(memex IMPLEMENT.md pitfall #1)"
                )
            return resp.read()

    def xFileSize(self) -> int:
        return self.size

    def xClose(self) -> None:
        pass

    def xLock(self, level):
        pass

    def xUnlock(self, level):
        pass

    def xFileControl(self, op, ptr):
        return False

    def xCheckReservedLock(self):
        return False

    def xSync(self, flags):
        pass

    def xTruncate(self, newsize):
        raise IOError("read-only VFS")

    def xWrite(self, data, offset):
        raise IOError("read-only VFS")


# Class body deferred behind a factory so a broken/incomplete apsw
# install (e.g. missing native VFS support) fails at call time with a
# clear message instead of crashing this module's import.
def _make_http_range_vfs_class():
    class HttpRangeVFS(apsw.VFS):
        def __init__(self, name="http-range-vfs"):
            self.files: dict[str, HttpRangeFile] = {}
            super().__init__(name=name, base="")

        def xOpen(self, name, flags):
            url = str(name)
            f = HttpRangeFile(url)
            self.files[url] = f
            return f

        def xAccess(self, pathname, flags):
            return True

        def xFullPathname(self, name):
            return str(name)

    return HttpRangeVFS


def query_over_http(release: str, base_url: str, sql: str, params: tuple = ()) -> tuple:
    if apsw is None:
        raise SystemExit("APSW not installed -- run: pip install apsw")
    if not hasattr(apsw, "VFS"):
        raise SystemExit(
            "apsw is installed but this build has no VFS support "
            "(apsw.VFS is missing) -- can't run the HTTP-range spike. "
            "Path 1 (examples/query.py) remains the shipped default."
        )

    url = f"{base_url}/{release}/index.db"
    vfs = _make_http_range_vfs_class()()
    conn = apsw.Connection(url, vfs=vfs.name, flags=apsw.SQLITE_OPEN_READONLY)
    conn.pragma("page_size", PAGE_SIZE)
    cur = conn.cursor()
    rows = list(cur.execute(sql, params))

    handle = vfs.files.get(url)
    report = {
        "requests": handle.request_count if handle else 0,
        "bytes_fetched": handle.bytes_fetched if handle else 0,
        "db_size": handle.size if handle else 0,
    }
    conn.close()
    return rows, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("release", help="e.g. 1.94.1")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = ap.parse_args()

    if apsw is None:
        print("APSW not installed -- run: pip install apsw", file=sys.stderr)
        print("This is a SPIKE per issue #1; Path 1 (examples/query.py) is the "
              "shipped default and needs no extra dependency.", file=sys.stderr)
        return 1

    sql = """
        SELECT documents.path, chunks.heading
        FROM search_porter
        JOIN chunks ON chunks.rowid = search_porter.rowid
        JOIN documents ON documents.doc_id = chunks.doc_id
        WHERE search_porter MATCH ?
        ORDER BY bm25(search_porter)
        LIMIT 5
    """
    rows, report = query_over_http(
        args.release, args.base_url,
        sql, ("fingerprint AND (input OR hash OR dirty OR fresh)",),
    )
    print(f"rows: {rows}")
    print(f"HTTP range report: {report['requests']} requests, "
          f"{report['bytes_fetched']} bytes fetched of {report['db_size']} total "
          f"({100 * report['bytes_fetched'] / max(report['db_size'], 1):.2f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
