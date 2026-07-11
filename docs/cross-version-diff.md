# Cross-version diffing

Every release gets its own `index.db` (see `queries.md` + issue #1's
"One DB per version" section) -- there is no monolithic all-versions
database. Two ways to compare releases:

## 1. Zero-network file/manifest diff

```sh
diff -ru source/1.94.1 source/1.95.0
diff <(jq .anchors source/1.94.1/manifest.json) <(jq .anchors source/1.95.0/manifest.json)
```

## 2. Local/CLI: `ATTACH` + `UNION ALL` (guaranteed to work)

```sql
ATTACH 'site/1.94.1/index.db' AS v1941;
ATTACH 'site/1.95.0/index.db' AS v1950;

SELECT 'v1941' AS release, d.path, c.heading
FROM v1941.chunks c
JOIN v1941.search_porter ON search_porter.rowid = c.rowid
JOIN v1941.documents d ON d.doc_id = c.doc_id
WHERE search_porter MATCH 'fingerprint AND hash'
UNION ALL
SELECT 'v1950', d.path, c.heading
FROM v1950.chunks c
JOIN v1950.search_porter ON search_porter.rowid = c.rowid
JOIN v1950.documents d ON d.doc_id = c.doc_id
WHERE search_porter MATCH 'fingerprint AND hash';
```

**Gotcha (SQLite quirk worth knowing):** the `MATCH` operand must be the
**unqualified** FTS5 table name (or its bare alias) -- `v1941.search_porter
MATCH '...'` fails with `no such column: v1941.search_porter`, even
though the same table is reachable schema-qualified everywhere else in
the query (`FROM v1941.search_porter`, `JOIN v1941.chunks`, etc.). Write
`search_porter MATCH '...'` and let the `FROM`/`JOIN` clauses supply the
schema qualification instead. Verified against SQLite 3.50.4.

Confirmed working locally with `python -c "..."` against `site/1.94.1/index.db`
and `site/1.95.0/index.db` -- both releases' `fingerprint/mod.rs` hits
returned correctly tagged by release in one `UNION ALL` result set.

## 3. In-browser over HTTP range (spike, per issue #1 -- NOT attempted here)

memex's `openMemexDb(url)` builds one HTTP backend per `file:<url>` open;
whether `ATTACH 'file:https://.../1.95.0/index.db?vfs=http' AS v1950`
works against a *second* memex-opened database is undocumented and
untested in memex itself (tracked as `zackees/memex#11`). Not attempted
as part of this repo's build -- default UX loads one version at a time;
if the spike fails, the fallback is opening each version's DB
sequentially and merging results in JS (always works, at the cost of
one extra round of requests per additional version compared).
