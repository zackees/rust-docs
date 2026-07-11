"""Resolve anchors + fetch verbatim docs for one Rust release.

Given a release string (e.g. "1.94.1"), resolves the four anchors
declared in docs_manifest.yaml (rust tag, cargo submodule pin,
rustc-dev-guide nearest-commit-before-release-date, sccache latest
release tag), downloads every listed file verbatim via
raw.githubusercontent.com at the pinned commit, and writes
source/<release>/ + source/<release>/manifest.json.

All sources have a clean upstream Markdown/.rs original -- no HTML
scraping (see issue #1). Network calls go through the GitHub REST API
(for ref resolution) and raw.githubusercontent.com (for file bytes);
both are stdlib-only (urllib), using GITHUB_TOKEN if present to avoid
anonymous rate limits.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    raise SystemExit("PyYAML is required: pip install pyyaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_YAML = Path(__file__).resolve().parent / "docs_manifest.yaml"
SOURCE_DIR = REPO_ROOT / "source"

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()


def _api_get(path: str) -> dict | list:
    url = f"{GITHUB_API}{path}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API {e.code} for {url}: {body}") from e


def _headers() -> dict:
    h = {
        "User-Agent": "rust-docs-fetch-docs/1.0",
        "Accept": "application/vnd.github+json",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} fetching {url}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"URL error fetching {url}: {e}") from e


def resolve_rust_tag(release: str) -> tuple[str, str]:
    """Return (commit_sha, iso_committed_date) for the rust-lang/rust tag == release."""
    ref = _api_get(f"/repos/rust-lang/rust/git/refs/tags/{release}")
    sha = ref["object"]["sha"]
    if ref["object"]["type"] == "tag":
        tag_obj = _api_get(f"/repos/rust-lang/rust/git/tags/{sha}")
        sha = tag_obj["object"]["sha"]
    commit = _api_get(f"/repos/rust-lang/rust/commits/{sha}")
    date = commit["commit"]["committer"]["date"]
    return sha, date


def resolve_cargo_submodule(rust_release: str) -> str:
    """Return the commit SHA of src/tools/cargo pinned at rust-lang/rust@<release>."""
    entry = _api_get(f"/repos/rust-lang/rust/contents/src/tools/cargo?ref={rust_release}")
    return entry["sha"]


def resolve_devguide_commit(before_iso: str) -> str:
    """Return the nearest rustc-dev-guide commit at/before `before_iso`."""
    commits = _api_get(f"/repos/rust-lang/rustc-dev-guide/commits?until={before_iso}&per_page=1")
    if not commits:
        raise SystemExit(f"no rustc-dev-guide commit found before {before_iso}")
    return commits[0]["sha"]


def resolve_sccache_tag() -> tuple[str, str]:
    """Return (tag_name, commit_sha) for sccache's latest release."""
    rel = _api_get("/repos/mozilla/sccache/releases/latest")
    tag = rel["tag_name"]
    ref = _api_get(f"/repos/mozilla/sccache/git/refs/tags/{tag}")
    sha = ref["object"]["sha"]
    if ref["object"]["type"] == "tag":
        tag_obj = _api_get(f"/repos/mozilla/sccache/git/tags/{sha}")
        sha = tag_obj["object"]["sha"]
    return tag, sha


def _load_manifest_yaml() -> dict:
    return yaml.safe_load(MANIFEST_YAML.read_text(encoding="utf-8"))


def _fetch_file(repo: str, commit: str, path: str, dest_dir: Path) -> dict:
    url = f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"
    data = _download_bytes(url)
    dest = dest_dir / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    sha256 = hashlib.sha256(data).hexdigest()
    return {
        "path": str((dest_dir.relative_to(SOURCE_DIR) / path).as_posix()),
        "url": url,
        "sha256": sha256,
        "size_bytes": len(data),
    }


def resolve_anchors(release: str) -> dict:
    rust_sha, rust_date = resolve_rust_tag(release)
    cargo_sha = resolve_cargo_submodule(release)
    devguide_sha = resolve_devguide_commit(rust_date)
    sccache_tag, sccache_sha = resolve_sccache_tag()
    return {
        "rust": {"repo": "rust-lang/rust", "tag": release, "commit": rust_sha,
                 "release_date": rust_date},
        "cargo": {"repo": "rust-lang/cargo", "commit": cargo_sha,
                  "resolved_via": f"rust-lang/rust@{release}:src/tools/cargo submodule"},
        "rustc-dev-guide": {"repo": "rust-lang/rustc-dev-guide", "commit": devguide_sha,
                             "anchor_policy": "nearest-commit-before-release-date"},
        "sccache": {"repo": "mozilla/sccache", "tag": sccache_tag, "commit": sccache_sha},
    }


def fetch_release(release: str) -> Path:
    manifest_yaml = _load_manifest_yaml()
    anchors = resolve_anchors(release)
    dest_dir = SOURCE_DIR / release
    dest_dir.mkdir(parents=True, exist_ok=True)

    files: list[dict] = []

    for name in ("rust", "cargo", "rustc-dev-guide", "sccache"):
        anchor_cfg = manifest_yaml["anchors"][name]
        repo = anchor_cfg["repo"]
        commit = anchors[name]["commit"]
        anchor_dest = dest_dir / name
        for rel_path in anchor_cfg["files"]:
            print(f"[fetch] {name}: {rel_path} @ {commit[:12]}")
            files.append(_fetch_file(repo, commit, rel_path, anchor_dest))

    # rustc source paths live under the `rust` anchor, same commit.
    rust_commit = anchors["rust"]["commit"]
    rust_dest = dest_dir / "rust"
    for rel_path in manifest_yaml.get("rustc_source_paths", []):
        print(f"[fetch] rust (source): {rel_path} @ {rust_commit[:12]}")
        files.append(_fetch_file("rust-lang/rust", rust_commit, rel_path, rust_dest))

    manifest = {
        "kind": "CorpusSnapshot",
        "schema_version": 1,
        "release": release,
        "anchors": anchors,
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": files,
    }
    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    print(f"\nwrote {manifest_path} ({len(files)} files)")
    return manifest_path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: fetch_docs.py <release, e.g. 1.94.1>")
    fetch_release(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
