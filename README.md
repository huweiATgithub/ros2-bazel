# ROS 2 + Rust with Bazel

[![Ubuntu 24.04 CI](https://github.com/huweiATgithub/ros2-bazel/actions/workflows/ci.yml/badge.svg)](https://github.com/huweiATgithub/ros2-bazel/actions/workflows/ci.yml)

Ubuntu 24.04 is the first tested platform; this repository can grow to cover other distributions.

A core-only compatibility experiment with [ROS Central Registry](https://github.com/openrobotics/ros-central-registry). No installed ROS distribution, colcon, Cargo invocation, CMake invocation, or desktop stack is used. Bazel drives C++, Rust, Python, code generation and tests.

## What the test proves

- A C++ ROS node statically links a Rust library through a small C ABI.
- Rust computes `n² + 3n + 7`; the node publishes 40 numbered results after discovering two independent C++ subscribers.
- Each subscriber checks every sequence number and result with an independent C++ oracle, then checks checksum 23160. Missing, reordered or corrupt samples fail.
- A C++ client verifies an absent-service timeout, waits for a delayed server, and checks 12 alternating service calls against exact expected Rust results.
- Python ROS `launch_testing` manages the four processes, asserts their observable results and checks all exit codes, including graceful server shutdown.
- Rust unit tests also run as a Bazel test.

## Run

On x86_64 Ubuntu 24.04, install curl, ca-certificates, unzip, zip and xz-utils, then install Bazelisk from its official release. `.bazelversion` selects Bazel 9.0.0.

```sh
bazel test //:tests --test_output=errors --nocache_test_results
```

No `source /opt/ros/...` step is needed. DDS requires permission to enumerate network interfaces and communicate over local UDP. The integration test uses ROS domain 93 and localhost-only discovery; do not run concurrent copies in that domain. Test deadlines are bounded; subscriber or service timeouts fail the test.

## Monorepo packages and dependencies

One root `MODULE.bazel` owns external dependencies and toolchains. Each directory below is a separate **Bazel package**, with its own `BUILD.bazel` and targets:

```text
MODULE.bazel                    # one Bzlmod module, shared toolchains/dependency versions
BUILD.bazel                     # //:tests aggregates the two test targets
libs/
  demo_protocol/                # :protocol, shared C++ topic/service names and counts
  rust_math/                    # :rust_math C API, private :rust_math_impl, :rust_math_test
apps/
  producer/                     # :producer, C++ ROS node calling Rust
  observer/                     # :observer, independent C++ result verifier
  client/                       # :client, C++ service verifier
tests/integration/              # :launch_integration_test, Python process-level test
examples/cli/                   # :demo build aggregate plus run_cli_demo.sh
```

A [Bazel package](https://bazel.build/concepts/build-ref#packages) is a source/build boundary, not a separate Bzlmod module. A [Bzlmod module](https://bazel.build/external/module) is the dependency-versioning unit described by `MODULE.bazel`; do not add one per local package. A ROS package normally has `package.xml` metadata for the ROS ecosystem. These local packages deliberately use Bazel only, not a colcon/ament workspace; ROS dependencies such as `rclcpp`, `std_msgs`, and `std_srvs` come from RCR as external modules. The terms are not interchangeable.

The local dependency graph is small and explicit:

```text
apps/producer:producer -> libs/rust_math:rust_math -> :rust_math_impl (Rust)
                      -> libs/demo_protocol:protocol
apps/observer:observer -> libs/demo_protocol:protocol
apps/client:client     -> libs/demo_protocol:protocol
tests/integration:launch_integration_test --data--> all three application binaries
examples/cli:demo --srcs--> CLI script + all three application binaries
```

For example, `apps/producer/BUILD.bazel` declares `deps = ["//libs/rust_math:rust_math", "//libs/demo_protocol:protocol", ...]`. The prefix `//` means this repository, `libs/rust_math` is the package, and `rust_math` after `:` is the target. Inside that library package, `:rust_math_impl` is a same-package label. `@rclcpp//:rclcpp_library` instead refers to an external repository.

The C++ `rust_math` interface exports `math.h` and transitively links the private Rust static library. Only the producer package can depend on it. The protocol library permits the three app packages; the binaries permit the integration-test and CLI-example packages. These [visibility](https://bazel.build/concepts/visibility) declarations enforce the boundaries rather than making everything public. They restrict dependencies, not explicit command-line builds.

The integration test declares executables in `data`, not `deps`, because they are runtime processes rather than Python imports. Its `$(rootpath //apps/producer:producer)` arguments resolve the declared binaries in Bazel's runfiles tree. The shared protocol header contains names and counts only: the observers' formula/checksum and the client's expected service responses remain independent of Rust.

Try the package-qualified targets and inspect their dependencies:

```sh
bazel build //apps/producer:producer
bazel test //libs/rust_math:rust_math_test
bazel test //tests/integration:launch_integration_test --test_output=errors
bazel query 'labels(deps, //apps/producer:producer)'
bazel query 'labels(deps, //libs/rust_math:rust_math)'
```

## How it works

- **Build dependencies, not a sourced workspace:** `MODULE.bazel` resolves ROS packages from RCR and other dependencies from BCR. Each package's `BUILD.bazel` declares its targets' libraries and runtime data. Bazel supplies the compiler, Rust and Python toolchains and dependency paths; it does not generate a colcon-style `install/setup.bash` or require an installed ROS distribution.
- **Runtime files still matter:** Bazel assembles each target's declared runtime files in a `.runfiles` tree. RCR's `ament_index` rules arrange resources/plugins there like a ROS prefix, and its patched lookup code can find that tree without a sourced `AMENT_PREFIX_PATH`. `bazel run`/`bazel test` provide the runfiles context; an already-set `AMENT_PREFIX_PATH` is still respected, so use a fresh, unsourced shell.
- **This demo is simpler:** `.bazelrc` selects CycloneDDS at build time and uses `--dynamic_mode=off`, linking the ROS libraries, message typesupport and Rust code into these C++ executables. `RMW_IMPLEMENTATION` is not a runtime middleware switch for this build. ROS settings such as `ROS_DOMAIN_ID` and discovery range still apply. The executables are not fully static: the system loader/glibc and compatible OS/architecture are still required.

### Run the built binaries from a shell

From the repository root in a fresh shell:

```sh
bazel build //examples/cli:demo
timeout --signal=TERM --kill-after=5s 60s bash examples/cli/run_cli_demo.sh
```

`//examples/cli:demo` is a build-only `filegroup` whose `srcs` aggregate the script and all three binaries. The [CLI example](examples/cli/run_cli_demo.sh) runs `./bazel-bin/apps/producer/producer`, two copies of `./bazel-bin/apps/observer/observer`, and `./bazel-bin/apps/client/client` directly, without `bazel run`, `launch_testing`, `ros2 run` or sourcing ROS. It checks all four exit codes, both subscribers' `RECEIVED 40 CHECKSUM 23160`, the client's `SERVICE_PASS 12`, and the producer's output, then shuts the producer down. Logs are saved in `cli-logs/`. CI runs these same commands after the build, separately from the Bazel tests. It uses localhost discovery and domain 94 by default; choose a different unused domain with `ROS_DOMAIN_ID=95 timeout ...` for a concurrent run.

For interactive use, set the same environment in **four terminals**, all at the repository root:

```sh
export ROS_DOMAIN_ID=94 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
# Run one command per terminal:
./bazel-bin/apps/producer/producer
./bazel-bin/apps/observer/observer --ros-args -r __node:=observer_one
./bazel-bin/apps/observer/observer --ros-args -r __node:=observer_two
./bazel-bin/apps/client/client
```

Start all four within 25 seconds. After both observers and the client finish successfully, press Ctrl-C in the producer terminal. The producer waits for two subscribers and expects exactly 12 service calls before a successful shutdown. Alternatively, `bazel run //apps/producer:producer -- --ros-args -r __node:=my_producer` builds and starts that target in Bazel's runtime context, passing arguments after `--`.

Keep the build outputs and adjacent runfiles together. Direct execution of these C++ demos does not mean every ROS/Python/plugin target is a standalone file; declare its runtime data and package the complete runtime tree for deployment. See RCR's [runtime-data](https://github.com/openrobotics/ros-central-registry#runtime-data) and [static-compilation](https://github.com/openrobotics/ros-central-registry#static-compilation) explanations.

## Versions and scope

The root requests `ros_core lyrical.2026-06-08.rcr.2`. Bazel minimum-version selection can select later compatible transitive module versions: the baseline resolved `rosdistro lyrical.2026-06-08.rcr.8`. The checked-in lockfile records registry resolution, not OS certification. LLVM and Python toolchains are downloaded by Bazel; Rust is pinned to 1.93.0. CycloneDDS is selected as the RMW.

The registry's full module graph contains optional desktop dependencies, but this repository does not build its desktop examples. Runtime binaries link only the selected core dependencies and Rust logic. `--dynamic_mode=off` does not make glibc fully static.

## Build profiling in CI

CI measures the initial application build on a fresh Ubuntu 24.04 runner, then repeats the identical build twice in the same workspace/server to show warm-cache behavior. Test execution is still forced with `--nocache_test_results`; the direct CLI check remains separate. This is not a cross-runner cache benchmark.

The [profiling wrapper](tools/ci/profile_bazel.sh) records Bazel JSON traces, Build Event Protocol metrics, console logs and elapsed times. The `ubuntu24-bazel-profiles` artifact contains those files, runner details and a [generated phase/action summary](tools/ci/summarize_bazel_profiles.py). OS setup and Bazel startup are timed separately. Action durations may overlap, so do not sum them as wall-clock time.

## Baseline validation (2026-10-20)

Before the package refactor, [GitHub Actions run 39426065208](https://github.com/huweiATgithub/ros2-bazel/actions/runs/39426065208) passed on the native `ubuntu-24.04` runner at commit `30033f1b8fd4ddbed7548c87e07a078a17957b88`.

- Full C++/Rust build and both Bazel test targets passed: 410 seconds, 4065 actions.
- `launch_integration_test` passed in 2.8 seconds, checking both subscribers, all 12 service responses, the absent-service timeout and clean process exit.
- `rust_math_test` passed. No test results were reused (`--nocache_test_results`).
- Test logs and JUnit XML are available in the run's `ubuntu24-test-results` artifact.

The first run built and communicated successfully but exposed a harness mistake: `launch_testing` output assertions default to stderr, while the demos write stdout. The corrected assertions explicitly select stdout; no communication checks were removed or weakened. The failed run also confirmed that a failing launch assertion propagates to a failing Bazel test.

This establishes the demonstrated core-only workload on Ubuntu 24.04, not full ROS platform certification, desktop support or compatibility with every package or hardware driver. The earlier local sandbox denied DDS interface enumeration; GitHub CI provided the unrestricted local networking needed for the actual runtime test.
