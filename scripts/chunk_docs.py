"""Chunk verbatim source/<release>/ docs into per-document JSON records.

Replaces datasheets' pypdf page-extractor: our sources are already text,
so this just splits each file into logically-addressable chunks with a
`heading` anchor:

  - `.md`  -> split on ATX headings (`#`..`######`); each chunk is one
             heading + the text up to the next heading.
  - `.rs`  -> split on top-level items (fn/struct/enum/trait/impl/mod/
             type/const/static at column 0), each chunk carries its
             immediately preceding `///` doc-comment block; a leading
             `//!` module doc-comment becomes its own chunk.
  - anything else -> one whole-file chunk.

Output: _cache/<release>/chunks/<doc-index>.json, one file per source
document, `{"path": ..., "chunks": [{"heading": ..., "text": ...}, ...]}`.
build_index.py reads these + source/<release>/manifest.json to populate
`documents` / `chunks` / `document_text`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "source"
CACHE_DIR = REPO_ROOT / "_cache"

MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
RS_ITEM_RE = re.compile(
    r"^(?:pub(?:\([^)]*\))?\s+)?"
    r"(fn|struct|enum|trait|impl|mod|type|const|static)\b\s*(.*)$"
)


def _chunk_markdown(text: str) -> list[dict]:
    lines = text.splitlines()
    chunks: list[dict] = []
    heading = "(preamble)"
    buf: list[str] = []

    def _flush():
        body = "\n".join(buf).strip()
        if body:
            chunks.append({"heading": heading, "text": body})

    for line in lines:
        m = MD_HEADING_RE.match(line)
        if m:
            _flush()
            heading = m.group(2).strip()
            buf = [line]
        else:
            buf.append(line)
    _flush()
    return chunks


def _item_heading(sig_line: str) -> str:
    return sig_line.strip().rstrip("{").strip()


def _chunk_rust(text: str) -> list[dict]:
    lines = text.splitlines()
    chunks: list[dict] = []

    # Leading module doc-comment (//! block) becomes its own chunk.
    i = 0
    module_doc: list[str] = []
    while i < len(lines) and (lines[i].startswith("//!") or lines[i].strip() == ""):
        if lines[i].startswith("//!"):
            module_doc.append(lines[i])
        i += 1
        if lines[i - 1].strip() == "" and module_doc:
            # allow at most one blank line inside the doc block, otherwise stop
            if i < len(lines) and not lines[i].startswith("//!"):
                break
    if module_doc:
        chunks.append({"heading": "(module doc)", "text": "\n".join(module_doc)})

    pending_doc: list[str] = []
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("///"):
            pending_doc.append(line)
            i += 1
            continue
        if not line.startswith(" ") and not line.startswith("\t") and RS_ITEM_RE.match(line):
            sig = line
            body_lines = [line]
            depth = line.count("{") - line.count("}")
            j = i + 1
            has_brace = "{" in line
            terminated = line.rstrip().endswith(";") and not has_brace
            while j < n and not terminated and (not has_brace or depth > 0):
                nxt = lines[j]
                body_lines.append(nxt)
                depth += nxt.count("{") - nxt.count("}")
                if "{" in nxt:
                    has_brace = True
                if has_brace and depth <= 0:
                    j += 1
                    break
                if not has_brace and nxt.rstrip().endswith(";"):
                    j += 1
                    break
                j += 1
            full = "\n".join(pending_doc + body_lines)
            chunks.append({"heading": _item_heading(sig), "text": full})
            pending_doc = []
            i = j
            continue
        if stripped == "":
            pending_doc = []
        i += 1

    if not chunks:
        chunks.append({"heading": "(file)", "text": text})
    return chunks


def chunk_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".md":
        return _chunk_markdown(text)
    if path.suffix == ".rs":
        return _chunk_rust(text)
    return [{"heading": "(file)", "text": text}]


def chunk_release(release: str) -> Path:
    release_dir = SOURCE_DIR / release
    manifest_path = release_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing {manifest_path}; run ingest.py {release} first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    out_dir = CACHE_DIR / release / "chunks"
    if out_dir.exists():
        for f in out_dir.glob("*.json"):
            f.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, entry in enumerate(manifest["files"]):
        rel_path = entry["path"]
        src = SOURCE_DIR / rel_path
        chunks = chunk_file(src)
        record = {"path": rel_path, "chunks": chunks}
        out_path = out_dir / f"{idx:04d}.json"
        out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    print(f"[chunk] {release}: {len(manifest['files'])} documents -> {out_dir}")
    return out_dir


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: chunk_docs.py <release, e.g. 1.94.1>")
    chunk_release(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
