#!/usr/bin/env bash
# Runtime-only example. Build with Bazel first, then invoke this script under:
# timeout --signal=TERM --kill-after=5s 60s bash examples/run_cli_demo.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p cli-logs

# Prove that these C++ applications do not depend on a sourced ROS workspace,
# Bazel's launcher environment, or a caller's Python/shared-library search path.
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH ROS_PACKAGE_PATH
unset PYTHONPATH LD_LIBRARY_PATH RUNFILES_DIR RUNFILES_MANIFEST_FILE TEST_WORKSPACE
unset RMW_IMPLEMENTATION  # CycloneDDS is selected at build time in .bazelrc.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-94}"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

pids=()
cleanup() {
  status=$?
  trap - EXIT INT TERM
  for pid in "${pids[@]}"; do kill -TERM "$pid" 2>/dev/null || true; done
  for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
  for log in cli-logs/*.log; do
    [[ -f "$log" ]] || continue
    printf '\n=== %s ===\n' "$log"
    cat "$log"
  done
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

./bazel-bin/observer --ros-args -r __node:=cli_observer_one >cli-logs/observer-one.log 2>&1 &
first=$!; pids+=("$first")
./bazel-bin/observer --ros-args -r __node:=cli_observer_two >cli-logs/observer-two.log 2>&1 &
second=$!; pids+=("$second")
./bazel-bin/client >cli-logs/client.log 2>&1 &
client=$!; pids+=("$client")
# Exercise waiting for a late service provider, as well as direct execution.
sleep 1
./bazel-bin/producer >cli-logs/producer.log 2>&1 &
producer=$!; pids+=("$producer")

# Any nonzero exit or missing expected output fails this example and CI.
wait "$first"
wait "$second"
wait "$client"
grep -Fxq 'RECEIVED 40 CHECKSUM 23160' cli-logs/observer-one.log
grep -Fxq 'RECEIVED 40 CHECKSUM 23160' cli-logs/observer-two.log
grep -Fxq 'ABSENT_SERVICE_TIMEOUT_OK' cli-logs/client.log
grep -Fxq 'SERVICE_PASS 12' cli-logs/client.log
grep -Fxq 'PUBLISHED 40' cli-logs/producer.log
grep -Fxq 'SERVICE 12 425' cli-logs/producer.log

# rclcpp handles SIGTERM gracefully; wait checks the actual producer exit code.
kill -TERM "$producer"
wait "$producer"
pids=()
echo 'CLI_DEMO_PASS: two subscribers, 12 service calls, four clean exits'
