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
bazel test //:rust_math_test //:launch_integration_test --test_output=errors --nocache_test_results
```

No `source /opt/ros/...` step is needed. DDS requires permission to enumerate network interfaces and communicate over local UDP. The integration test uses ROS domain 93 and localhost-only discovery; do not run concurrent copies in that domain. Test deadlines are bounded; subscriber or service timeouts fail the test.

## Versions and scope

The root requests `ros_core lyrical.2026-06-08.rcr.2`. Bazel minimum-version selection can select later compatible transitive module versions: the baseline resolved `rosdistro lyrical.2026-06-08.rcr.8`. The checked-in lockfile records registry resolution, not OS certification. LLVM and Python toolchains are downloaded by Bazel; Rust is pinned to 1.93.0. CycloneDDS is selected as the RMW.

The registry's full module graph contains optional desktop dependencies, but this repository does not build its desktop examples. Runtime binaries link only the selected core dependencies and Rust logic. `--dynamic_mode=off` does not make glibc fully static.

## Validation status

CI is configured for a native GitHub-hosted `ubuntu-24.04` runner. Check the Actions run for the actual result; configuration alone is not evidence of a passing run. A prior simpler C++-only experiment built on official Ubuntu 24.04.3 userspace without ROS source patches. That environment denied DDS interface enumeration, so it did not establish runtime success. This expanded Rust/launch suite is a separate test and must pass CI before runtime compatibility is claimed.
