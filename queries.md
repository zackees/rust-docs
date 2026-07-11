# Canned caching queries

Pre-baked FTS5 `search_porter` queries for the caching questions people
actually ask about Cargo/rustc. Used as the UI example searches and as
relevance regression tests in `tests/test_queries.py` (each must return
its target doc, run against every release DB).

1. **What inputs go into a unit fingerprint?**
   ```
   fingerprint AND (input OR hash OR dirty OR fresh)
   ```
   Target doc(s): `fingerprint/mod.rs`, `build-cache.md`

2. **Where does Cargo persist freshness state on disk (.fingerprint/)?**
   ```
   "fingerprint" AND (directory OR json OR "on disk" OR store)
   ```
   Target doc(s): `fingerprint/mod.rs`, `build-cache.md`

3. **What lives in target/, deps/, incremental/; rlib/rmeta linking layout?**
   ```
   target AND (deps OR incremental OR rlib OR rmeta)
   ```
   Target doc(s): `build-cache.md`, `compilation_files.rs`

4. **How does Cargo track discovered source inputs via dep-info .d files?**
   ```
   "dep info" OR ("d files") OR (discovered AND dependency)
   ```
   Target doc(s): `dep_info.rs`, `build-cache.md`

5. **How are --extern dependencies identified (path/contents/crate hash)?**
   ```
   extern AND (rmeta OR rlib OR metadata OR hash)
   ```
   Target doc(s): `compilation_files.rs`, `locator.rs`, `creader.rs`

6. **When does a build script re-run (rerun-if-changed / -env-changed)?**
   ```
   ("rerun if changed") OR ("rerun if env changed") OR ("build script" AND rerun)
   ```
   Target doc(s): `build-scripts.md`, `custom_build.rs`

7. **What invalidates the cache besides source -- rustflags/profile/features/LTO/codegen-units?**
   ```
   (rustflags OR profile OR feature OR lto OR "codegen units") AND (hash OR fingerprint OR metadata)
   ```
   Target doc(s): `fingerprint/mod.rs`, `compile_kind.rs`

8. **How to make artifacts path-independent for cross-workspace cache sharing?**
   ```
   ("remap path prefix") OR (remap AND path AND (prefix OR portable))
   ```
   Target doc(s): `command-line-arguments.md`, `dep_info.rs`

9. **Metadata pipelining -- when can a downstream crate start before .rlib is done?**
   ```
   (pipelin OR metadata) AND (rmeta OR ready OR "job queue")
   ```
   Target doc(s): `job_queue/mod.rs`, `libs-and-metadata.md`

10. **When is .rmeta enough vs .rlib required?**
   ```
   rmeta AND rlib AND (link OR downstream OR codegen)
   ```
   Target doc(s): `libs-and-metadata.md`, `compilation_files.rs`

11. **Can incremental state be relocated between machines/dirs?**
   ```
   incremental AND (relocat OR portab OR "work product" OR "dependency graph")
   ```
   Target doc(s): `incremental-compilation.md`, `codegen-options/index.md`

12. **Which crate types invoke the linker / what is unsafe to cache?**
   ```
   ("proc-macro" OR dylib OR cdylib OR bin) AND (link OR cache OR "not cacheable")
   ```
   Target doc(s): `Rust.md`, `rust.rs`, `back/link.rs`

13. **What's inside rustc's incremental on-disk cache (dep-graph, query results, work products)?**
   ```
   incremental AND ("work product" OR "dep graph" OR "query cache" OR serialized)
   ```
   Target doc(s): `incremental-compilation.md`, `serialization.md`

14. **How do -C metadata / -C extra-filename disambiguate symbols + output filenames?**
   ```
   ("extra filename") OR ("C metadata") OR (disambiguator AND crate)
   ```
   Target doc(s): `command-line-arguments.md`, `codegen-options/index.md`, `compilation_files.rs`

15. **.rmeta format + how a crate's SVH/hash is validated on load?**
   ```
   (rmeta OR metadata) AND (header OR version OR svh OR "strict version" OR validate)
   ```
   Target doc(s): `rmeta/mod.rs`, `locator.rs`, `libs-and-metadata.md`

16. **How does rustc locate + load crates (-L search paths, --extern, rlib/rmeta/dylib)?**
   ```
   (locate OR load) AND crate AND (extern OR "search path" OR rlib OR rmeta OR dylib)
   ```
   Target doc(s): `locator.rs`, `creader.rs`, `command-line-arguments.md`

17. **mtime vs checksum freshness -- how does Cargo decide a file changed?**
   ```
   (mtime OR timestamp OR modified OR checksum) AND (fresh OR fingerprint OR rebuild)
   ```
   Target doc(s): `fingerprint/mod.rs`, `build-cache.md`

18. **How are env vars tracked (env!, rerun-if-env-changed, RUSTFLAGS) in the key?**
   ```
   (env OR environment OR rustflags) AND (variable OR "rerun if env changed" OR track OR fingerprint)
   ```
   Target doc(s): `fingerprint/mod.rs`, `custom_build.rs`, `build-scripts.md`

19. **How are include! / include_bytes! / include_str! inputs tracked?**
   ```
   (include OR "include str" OR "include bytes") AND (dep OR track OR source OR rerun)
   ```
   Target doc(s): `dep_info.rs`, `build-cache.md`

20. **How does a dependency's fingerprint propagate -- an upstream change dirtying dependents?**
   ```
   fingerprint AND (dependency OR upstream OR propagat OR transitive) AND (dirty OR invalidat OR recompil)
   ```
   Target doc(s): `fingerprint/mod.rs`, `unit_dependencies.rs`

21. **.rlib archive internals -- object files, metadata object, symbol table?**
   ```
   rlib AND (archive OR object OR "symbol table" OR member)
   ```
   Target doc(s): `back/archive.rs`, `back/metadata.rs`, `libs-and-metadata.md`

22. **Debug-info sidecars -- -C split-debuginfo, .dwo / .pdb / .dSYM?**
   ```
   ("split debuginfo") OR (debuginfo AND (dwo OR pdb OR dsym OR split))
   ```
   Target doc(s): `codegen-options/index.md`, `back/link.rs`

23. **How do codegen-units affect object outputs + determinism?**
   ```
   ("codegen units") AND (object OR parallel OR determinis OR split)
   ```
   Target doc(s): `codegen-options/index.md`, `fingerprint/mod.rs`

24. **Cross-compile: host vs target -- build-deps + proc-macros built for the host?**
   ```
   ("build script" OR "proc macro" OR "build dependencies") AND host AND target
   ```
   Target doc(s): `compile_kind.rs`, `unit_dependencies.rs`, `build-cache.md`

25. **rustc's red-green algorithm -- when is a query result reused?**
   ```
   query AND (red OR green OR reuse OR "try mark green" OR "dep node")
   ```
   Target doc(s): `incremental-compilation.md`

26. **What --emit output types exist (metadata / link / obj / dep-info / llvm-*)?**
   ```
   emit AND (metadata OR link OR obj OR "dep info" OR llvm)
   ```
   Target doc(s): `command-line-arguments.md`

27. **Does panic strategy (abort/unwind) enter the cache key / affect ABI?**
   ```
   panic AND (abort OR unwind OR strategy) AND (fingerprint OR metadata OR abi)
   ```
   Target doc(s): `fingerprint/mod.rs`, `codegen-options/index.md`, `compilation_files.rs`, `back/link.rs`

