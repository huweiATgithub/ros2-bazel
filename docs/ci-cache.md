# Daily immutable Bazel caches

The Ubuntu 24.04 workflow uses `actions/cache/restore@v6` and
`actions/cache/save@v6`. Version 6 is the latest stable major verified on
20 October 2026 ([official release v6.1.0](https://github.com/actions/cache/releases/tag/v6.1.0)).
No remote-cache service, credentials or paid storage setting is configured.

## What is cached

- `$HOME/.cache/bazel-ci/repository`: downloaded external repository archives
  (`content_addressable/`) **and Bazel 9's fetched repository contents**
  (`contents/`), selected explicitly with `--repository_cache`.
- `$HOME/.cache/bazel-ci/disk`: Bazel action-result metadata and
  content-addressed outputs, selected explicitly with `--disk_cache`.

The workflow writes these flags into the ephemeral runner's user `.bazelrc`
before any Bazel command. It does **not** cache the Bazel server, output base,
workspace symlinks, execution/output trees or the entire home directory.
Module loading, extraction and analysis can still take time on a fresh runner.
The existing `--remote_upload_local_results=false` remains: no external Bazel
remote cache is enabled, while the local disk cache can still read and write.

`bazelbuild/setup-bazelisk@v3` has no cache-disable input in its
[action definition](https://github.com/bazelbuild/setup-bazelisk/blob/v3/action.yml).
Its legacy restore concerns only the downloaded Bazel executable, not these
repository or compiled-action caches. It is left unchanged rather than passing
an unsupported input.

## Daily key and fallback

The key has this structure:

```text
bazel-v1-<runner OS>-<runner architecture>-ubuntu24-<configuration hash>-YYYY-MM-DD
```

The configuration hash covers `.bazelversion`, `.bazelrc`, `MODULE.bazel`,
`MODULE.bazel.lock`, the CI workflow, profiling command wrapper and cache
pruning script. This
separates Bazel/toolchain/dependency/configuration changes. The explicit `v1`
prefix can be bumped to invalidate the cache schema. Application source files
are deliberately not in this outer key: Bazel's action keys track declared
inputs, commands, tools and environments, so changed actions rebuild instead
of blindly reusing stale outputs. As with all Bazel caching, correctness depends
on rules declaring their inputs and using hermetic tools.

The date is captured once in UTC at job start. Restore first looks for today's
exact key, then uses a prefix containing everything **except the date**.
There is no broader cross-configuration fallback.

1. If today's snapshot is absent, restore the most recently created accessible
   snapshot with the same prefix. Normally this is yesterday's, but it can be
   older when no successful run occurred yesterday or a cache was evicted.
2. Build, run the forced unit/launch tests, run the direct CLI check and inspect
   the configured dependency scope. Missing or invalidated action entries build
   normally and populate the local disk cache.
3. After all Bazel builds/tests and runtime checks, shut down Bazel and enforce
   the size budgets below. No later step may run Bazel against these caches.
   After pruning and artifact steps succeed, a trusted `push` or
   `workflow_dispatch` on `main` saves the bounded directories under today's
   key. Other branches and pull requests restore only.
4. The first successful save wins. Subsequent same-day exact hits skip saving;
   new entries produced later that day are not persisted in that immutable
   snapshot. Concurrent first runs can race for the same key; one wins without
   overwriting the other. The next UTC day gets a new key.

This is daily rotation **when CI runs**, not a scheduled daily build. Cache
misses are allowed and produce an ordinary build. No tests or build steps are
skipped because the GitHub cache reports an exact hit.

## Explicit snapshot size budgets

Every successfully saved snapshot is bounded independently of GitHub eviction:

- Repository downloads + fetched contents: **4 GiB** (4,294,967,296 bytes).
- Disk action results + output blobs: **2 GiB** (2,147,483,648 bytes).
- Combined cache trees: **at most 6 GiB**, before compression.

The limits are explicit job environment variables in `.github/workflows/ci.yml`.
The previous measured working set was approximately 3.5 GiB of repository cache
and 282 MiB of disk cache, so these limits preserve that working set with room
for changed actions while preventing unlimited accumulation across daily
snapshots. Archive compression usually makes GitHub storage smaller; the bound
is not a promise about peak disk use during a build, the uncached output base,
or the sum of historical GitHub snapshots.

`tools/ci/prune_bazel_cache.py` runs synchronously **after `bazel shutdown`** and
before saving. It uses only Python's standard library. It counts the larger of
logical length and allocated blocks for every entry, including directory
metadata and symlink text; hard links are conservatively counted separately.
It never follows symlinks. A final remeasurement must satisfy each limit, and
any shutdown, accounting or deletion failure prevents the save. The step uses
Bash's pipefail so writing the report through `tee` cannot hide a failure.

Entries too large to fit on their own are discarded first. Remaining entries
are evicted oldest-first, with path order breaking timestamp ties:

- Download entries are whole `content_addressable/<algorithm>/<digest>/`
  directories, including their canonical-ID markers. The downloaded `file`'s
  mtime records recent use.
- Fetched contents are whole `contents/<inputs-hash>/` directories, including
  every UUID tree and its `.recorded_inputs` marker. The newest marker's mtime
  is used. Files and meaningful empty directories inside a retained repository
  are never pruned independently.
- Disk entries are individual AC/CAS files, ordered like Bazel's own disk GC.
  Bazel 9.0.0 checks referenced output blobs before accepting an action hit;
  missing blobs cause a miss and rebuild, not an incomplete accepted result.

This collector is for the dedicated, quiescent CI directories, **not a shared
or live developer cache**. Bazel may symlink fetched repositories from the
output base into `repository/contents`, which is why shutdown and no later
Bazel commands are essential. Its idle GC flags alone do not guarantee that
collection finishes before a short CI job archives the cache. Bazel's normal
14-day fetched-contents age cleanup is not a byte limit and does not bound the
download cache. No background-GC delay or additional Bazel GC build dependency
is needed here.

Sources for the pinned Bazel 9.0.0 layout and semantics:
[repository downloads](https://github.com/bazelbuild/bazel/blob/9.0.0/src/main/java/com/google/devtools/build/lib/bazel/repository/cache/DownloadCache.java),
[fetched contents](https://github.com/bazelbuild/bazel/blob/9.0.0/src/main/java/com/google/devtools/build/lib/bazel/repository/cache/LocalRepoContentsCache.java),
[disk collector](https://github.com/bazelbuild/bazel/blob/9.0.0/src/main/java/com/google/devtools/build/lib/remote/disk/DiskCacheGarbageCollector.java),
[disk integrity checks](https://github.com/bazelbuild/bazel/blob/9.0.0/src/main/java/com/google/devtools/build/lib/remote/disk/DiskCacheClient.java).

The workflow runs collector regressions for missing/empty caches, both budgets,
oversized entries, deterministic order, marker/tree integrity, sparse files,
hard links, symlinks and rejected special files before building.

## Verification and limits

`ci-profiles/cache-restore.txt` records the requested key, matched key and exact
hit status. `cache-prune.json` records each limit, before/after accounted bytes
and number of evicted entries. `cache-sizes.txt` records post-prune `du` sizes. The action
logs show archive transfer/save details; workflow step timestamps give their
elapsed overhead. The profiler retains the first build as `initial-build`,
two unchanged same-server repeats and forced tests. A GitHub archive hit alone
does not prove that Bazel reused actions: inspect the initial build's action
counters and elapsed time.

The immediately preceding, genuinely uncached baseline is
[run 39458943515](https://github.com/huweiATgithub/ros2-bazel/actions/runs/39458943515)
at commit `849040a839b283ff81fd293e5900f21ed9c09a6c`: first build 365.274 s,
3,260 actions and 1,347 C++ compilations; unchanged same-workspace repeats
4.882 s and 0.498 s. These are not restored-cache results. The older
[profiling report](build-profile.md) analyzes an earlier dependency graph.
Measure a second fresh-runner cache restore before claiming a speedup. A
same-day rerun verifies exact-key restoration, not a real cross-day rollover.

GitHub's default repository cache allowance is 10 GB; inactive entries can
expire after seven days, and older entries can be evicted when storage fills.
Daily snapshots share that repository-wide budget, so several large copies
may evict each other. That historical-snapshot policy does not bound a restored
cache that is extended and saved again; the explicit pre-save byte budgets do. This change does not raise storage limits or enable
billing. See [GitHub's cache limits and key matching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
for current policy and branch visibility.

Cache contents are readable by workflows allowed to restore them, including
fork pull requests targeting the base branch. Do not place tokens, credentials
or private source data in either cached directory. Only trusted `main` runs
publish here; keep that trust boundary and the read-only repository token.
Bazel action keys are a correctness mechanism, not protection against a
malicious cache writer.
