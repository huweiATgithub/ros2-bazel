# ROS 2 + Rust runtime package

This archive is built by `bazel build //packaging:demo_archive` with
[`rules_pkg` 1.3.0](https://github.com/bazelbuild/rules_pkg/releases/tag/1.3).
It is a runtime bundle for **Ubuntu 24.04 x86_64**, not a ROS distribution,
SDK, fully static executable, or cross-platform installer.

## Run after extraction

From any working directory (adjust the package path):

```sh
python3 /path/to/ros2-bazel-demo/verify_runtime.py > runtime-inspection.json
timeout --signal=TERM --kill-after=5s 60s \
  python3 /path/to/ros2-bazel-demo/run_demo.py --log-dir "$PWD/package-logs"
```

No checkout, Bazel, compiler, Cargo, ROS installation, Python dependencies,
`launch_testing`, `rclpy`, or sourced workspace is needed. Python 3 uses only
its standard library. The optional audit needs `readelf` (binutils) and `ldd`;
Ubuntu 24.04 GitHub-hosted runners already provide them. Execution needs the
compatible system loader/glibc/C/C++ runtime libraries and local UDP/network
interface enumeration for DDS.

The runner starts two independent C++ subscribers and the service client,
then starts the producer late. Each subscriber checks all fields of 40 custom
messages and checksum 23160. The client checks the absent-service timeout and
12 service results. The script also verifies each alternating Rust result
(35, 425), checks all exit codes, and gracefully terminates the producer. It
has internal deadlines and bounded cleanup; the outer timeout is an additional
guard. Success ends with `PACKAGE_DEMO_PASS`. Logs are written outside the
package so the extracted payload can remain read-only.

Domain 96 and localhost discovery are used by default. For concurrent runs,
choose a distinct unused domain with `ROS_DOMAIN_ID=97 timeout ...`. The script
deliberately constructs a clean environment, without inherited ROS, Python,
runfiles, DDS configuration, or shared-library search paths.

## Layout and linkage

- `apps/{producer,observer,client}/`: executables and adjacent `.runfiles`
  directories, including declared runtime resources and repository mappings.
- `run_demo.py`: standalone runtime-only smoke runner.
- `verify_runtime.py`: inventory with SHA-256 hashes, symlink relocation checks,
  actual ELF interpreter/NEEDED/RPATH inspection, and `ldd` resolution checks.
- `runtime.json`: human-readable runtime contract and entrypoint list.

Keep the whole directory together. `pkg_tar(include_runfiles = True)` consumes
Bazel target providers, not host filesystem globs or producer-machine symlinks.
The tarball preserves modes and runtime-relative layout. The ROS libraries,
CycloneDDS, message typesupport and Rust implementation are linked into the C++
applications by this demo's `--dynamic_mode=off` configuration. That does **not**
make the ELF binaries fully static. The audit reports the actual dynamic
dependencies; only the documented system ABI library allowlist may resolve
outside the bundle. Missing or other undeclared external libraries fail.

The archive intentionally does not ship the original Python launch-test stack.
Those tests still run separately on the builder. A separate CI job downloads
only this archive, extracts it at a different absolute path, and audits/runs it
without checkout, builds, ROS setup or build-cache restore.

Source and build instructions:
https://github.com/huweiATgithub/ros2-bazel
