# Daily immutable Bazel caches

The Ubuntu 24.04 workflow uses `actions/cache/restore@v6` and
`actions/cache/save@v6`. Version 6 is the latest stable major verified on
20 October 2026 ([official release v6.1.0](https://github.com/actions/cache/releases/tag/v6.1.0)).
No remote-cache service, credentials or paid storage setting is configured.

## What is cached

- `$HOME/.cache/bazel-ci/repository`: downloaded external repository archives,
  selected explicitly with `--repository_cache`.
- `$HOME/.cache/bazel-ci/disk`: Bazel action-result metadata and
  content-addressed outputs, selected explicitly with `--disk_cache`.

The workflow writes these flags into the ephemeral runner's user `.bazelrc`
before any Bazel command. It does **not** cache the Bazel server, output base,
workspace symlinks, extracted execution trees or the entire home directory.
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
`MODULE.bazel.lock`, the CI workflow and the profiling command wrapper. This
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
3. After all checks/artifact steps succeed, a trusted `push` or
   `workflow_dispatch` on `main` saves the populated directories under today's
   key. Other branches and pull requests restore only.
4. The first successful save wins. Subsequent same-day exact hits skip saving;
   new entries produced later that day are not persisted in that immutable
   snapshot. Concurrent first runs can race for the same key; one wins without
   overwriting the other. The next UTC day gets a new key.

This is daily rotation **when CI runs**, not a scheduled daily build. Cache
misses are allowed and produce an ordinary build. No tests or build steps are
skipped because the GitHub cache reports an exact hit.

## Verification and limits

`ci-profiles/cache-restore.txt` records the requested key, matched key and exact
hit status. `cache-sizes.txt` records uncompressed directory sizes. The action
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
may evict each other. This change does not raise storage limits or enable
billing. See [GitHub's cache limits and key matching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
for current policy and branch visibility.

Cache contents are readable by workflows allowed to restore them, including
fork pull requests targeting the base branch. Do not place tokens, credentials
or private source data in either cached directory. Only trusted `main` runs
publish here; keep that trust boundary and the read-only repository token.
Bazel action keys are a correctness mechanism, not protection against a
malicious cache writer.
