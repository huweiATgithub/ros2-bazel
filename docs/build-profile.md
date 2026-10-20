# Bazel CI profiling: Ubuntu 24.04

Measured 20 October 2026, commit `0a7f216f0840cf5619ece5800e6a686cf4261a07`.

- [Successful run](https://github.com/huweiATgithub/ros2-bazel/actions/runs/39434584538)
- [Raw profiles, BEP, timings, logs and generated summaries](https://github.com/huweiATgithub/ros2-bazel/actions/runs/39434584538/artifacts/12269029445)
- [Test and CLI logs](https://github.com/huweiATgithub/ros2-bazel/actions/runs/39434584538/artifacts/12270091445)

## Conclusion

The slow CI is mainly a fresh-runner dependency build, not the small applications or tests. The initial build executes 4,045 actions, including 1,515 C/C++ compilations and 582 ROS IDL/type-support generation actions. Only 12 action-processing events belong to this workspace. Dependencies account for about 98.2% of cumulative action-processing duration.

The four-core runner is already almost fully occupied during execution: sampled system CPU averages approximately 3.74 cores, with local action concurrency near four. Raising `--jobs=4` alone is therefore not a promising first fix. The highest-value next experiment is persistent repository and action caching across CI runs, followed by measurement on a newly provisioned runner. No caching service, credentials, or production build settings were changed by this profiling work.

## Measured wall times

| Stage | Seconds |
| --- | ---: |
| OS prerequisites | 5.26 |
| Bazelisk setup, from workflow timestamps | 1.28 |
| Bazel binary download, extraction and server startup | 7.66 |
| Initial build, fresh runner | 344.26 |
| Unchanged repeat 1, same workspace/server | 3.48 |
| Unchanged repeat 2, same workspace/server | 0.43 |
| Bazel unit and launch tests, forced execution | 5.44 |
| Direct CLI integration demo | 2.24 |

Warm repeats are **same-workspace incremental builds**, not evidence of a cache restored on another CI runner. Both repeat builds execute zero compiler/linker subprocesses. All stages passed. The launch test itself took 2.683 seconds, and the Rust test 0.031 seconds.

## Cold-build phases

BEP reports 344.154 seconds inside Bazel, consistent with the 344.259-second external timer:

- Approximately 21.53 seconds before the analysis interval, mainly initialization, module resolution and loading.
- 38.60 seconds analysis.
- First build-action execution at 60.127 seconds.
- 283.954 seconds execution, approximately 82.5% of Bazel wall time.

Repository-fetch trace spans cover 40.945 seconds of the invocation. This is a union of overlapping repository/bootstrap operations, including extraction and repository logic, not pure network-transfer time, and it overlaps the above phases. The longest single repository-fetch span was the Rust toolchain at 14.777 seconds, followed by LLVM source at 6.104 seconds. Network activity was concentrated before build execution.

The generic BEP timing schema permits analysis/execution overlap; do not add these counters blindly for other invocations. For example, the test invocation overlaps its phases.

## Execution costs

Cumulative action-processing duration is 1,118.66 seconds across parallel work. It includes action overhead and is not CPU time or elapsed build time.

| Work | Count | Cumulative action-processing seconds |
| --- | ---: | ---: |
| C/C++ compilation | 1,515 | 714.31 |
| ROS IDL/type-support generation | 582 | 357.00 |
| Static archives | 387 | 6.37 |
| Linking | 22 | 1.64 |
| Rust compilation, all crates/tools | 3 | 2.89 |

BEP reports 641.46 CPU-seconds for C/C++ compilation (545.176 user plus 96.279 system). This independently supports compilation as the major cost.

Top dependency groups by cumulative action-processing duration:

- `rcl_interfaces`: 228.05 seconds, 915 actions.
- `rclcpp`: 218.74 seconds, 123 actions.
- `std_msgs`: 216.03 seconds, 844 actions.
- LLVM project/runtime libraries: 152.91 seconds, 577 actions.
- `type_description_interfaces`: 55.83 seconds, 242 actions.

The workspace's own work totals only 20.35 cumulative seconds: three C++ compiles (5.36, 5.89 and 7.82 seconds), one Rust static-library compile (0.205 seconds), three links (1.067 seconds combined), and five module-map writes. Some of these overlap.

## Critical path and utilization

Bazel's cold action critical path is 13.556 seconds, ending in the observer compile and link. It includes ROS type-description generation. The observer compile contributes 7.821 seconds on that path, and linking 0.375 seconds.

This does **not** mean the build could trivially finish in 14 seconds: the action critical path does not account for all preceding repository/analysis work, nor the total throughput cost of thousands of independent actions competing for four CPUs. The workload is dominated by aggregate compilation and generation throughput, rather than one long serial linker operation.

During execution, sampled system CPU averaged about 3.74 of four cores. Peak sampled system memory was approximately 3.25 GB on a runner with 15 GiB, so this run does not indicate memory exhaustion. These are sampled profiler counters, not a dedicated resource benchmark.

## Cache effectiveness

- Cold: 4,045 cache misses, of which 4,044 were `NOT_CACHED` and one was unconditional workspace-status work. All 2,607 spawned actions ran locally.
- First unchanged repeat: 3,427 action-cache hits and only the unconditional workspace-status action executed.
- Second unchanged repeat: in-memory graph reuse, no compiler/linker execution, just workspace-status work. The absence of an explicit cache-hit counter here does not imply a cache failure.
- The workflow has no explicit persistent Bazel repository or action cache. `setup-bazelisk@v3` reports a cache-restore HTTP 400 warning; its Bazelisk cache is not a compiled-action cache anyway. Bazel bootstrap was only 7.66 seconds, so that warning does not explain the several-minute compile.

## Recommended next steps

1. Preserve the measurements; they now run in CI and publish a dedicated artifact. Use the same targets and flags for comparisons.
2. Trial persistent repository and action/disk caching across fresh CI jobs, with an appropriately scoped key and storage budget. Measure restore/save overhead and cache hits on a second fresh runner before claiming the speedup.
3. Review broad interface dependencies if the registry exposes narrower targets. `@std_msgs//:cc` generates substantial work beyond a single message. Adding dedicated custom interfaces can keep application-owned scope small, but changing middleware/type-support policy needs its own correctness validation.
4. Consider more CPU only after caching is measured. Four jobs already substantially occupy the existing four-core runner.

The earlier unprofiled runs varied from about 262 to 436 seconds with similar action counts. The current 344-second cold result sits within that range. These are not controlled before/after samples, so this report does not claim that the package refactor improved or regressed cold performance.

## Reproduce

CI uses `tools/ci/profile_bazel.sh` for JSON traces, BEP and external wall timing. `tools/ci/summarize_bazel_profiles.py` processes them using only Python's standard library. This approach was validated against the installed Bazel 9 binary; `bazel analyze-profile` is no longer available in that binary. Load the `.profile.gz` traces into a compatible trace viewer for the full timeline.
