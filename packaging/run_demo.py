#!/usr/bin/env python3
"""Run only the extracted demo, using Python's standard library (not ROS Python)."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def require_line(path, expected):
    if expected not in path.read_text().splitlines():
        raise RuntimeError(f"{path.name}: missing {expected!r}")


def run_demo(root, log_dir, domain):
    log_dir.mkdir(parents=True, exist_ok=True)
    processes = {}
    logs = {}
    handles = []
    with tempfile.TemporaryDirectory(prefix="ros2-demo-home-") as home:
        # Do not inherit ROS, Python, shared-library, runfiles or DDS settings.
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": home,
            "ROS_DOMAIN_ID": domain,
            "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST",
        }

        def start(name, application, *args):
            logs[name] = log_dir / f"{name}.log"
            handle = logs[name].open("w")
            handles.append(handle)
            executable = root / "apps" / application / application
            processes[name] = subprocess.Popen(
                [str(executable), *args], cwd=home, env=env,
                stdout=handle, stderr=subprocess.STDOUT,
            )

        def wait_for_line(name, expected, deadline):
            while expected not in logs[name].read_text().splitlines():
                if processes[name].poll() is not None:
                    raise RuntimeError(f"{name} exited before {expected!r}")
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{name} did not report {expected!r}")
                time.sleep(0.05)

        try:
            start("observer-one", "observer", "--ros-args", "-r", "__node:=package_observer_one")
            start("observer-two", "observer", "--ros-args", "-r", "__node:=package_observer_two")
            start("client", "client")
            ready_deadline = time.monotonic() + 10
            wait_for_line("observer-one", "OBSERVER_READY", ready_deadline)
            wait_for_line("observer-two", "OBSERVER_READY", ready_deadline)
            wait_for_line("client", "ABSENT_SERVICE_TIMEOUT_OK", ready_deadline)
            # Start the server late, after the client's absent-service check.
            start("producer", "producer")
            deadline = time.monotonic() + 35
            for name in ("observer-one", "observer-two", "client"):
                code = processes[name].wait(timeout=max(0.01, deadline - time.monotonic()))
                if code != 0:
                    raise RuntimeError(f"{name} exited with {code}")
            for name in ("observer-one", "observer-two"):
                require_line(logs[name], "RECEIVED 40 CHECKSUM 23160 CUSTOM_FIELDS_OK")
            require_line(logs["client"], "SERVICE_PASS 12")
            # Publishing and response delivery may race stdout flushing in a
            # different process. Wait for the producer's final observations.
            wait_for_line("producer", "PUBLISHED 40", deadline)
            wait_for_line("producer", "SERVICE 12 425", deadline)
            for number in range(1, 13):
                expected = 35 if number % 2 else 425
                require_line(logs["producer"], f"SERVICE {number} {expected}")
            if processes["producer"].poll() is not None:
                raise RuntimeError("producer exited before graceful shutdown")
            processes["producer"].terminate()
            code = processes["producer"].wait(timeout=5)
            if code != 0:
                raise RuntimeError(f"producer exited with {code}")
        finally:
            # Cleanup is bounded even after an assertion, interrupt or timeout.
            for process in processes.values():
                if process.poll() is None:
                    process.terminate()
            cleanup_deadline = time.monotonic() + 3
            for process in processes.values():
                try:
                    process.wait(timeout=max(0.01, cleanup_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for handle in handles:
                handle.close()
            for name, path in logs.items():
                process = processes.get(name)
                code = process.returncode if process else "not started"
                print(f"\n=== {name} (exit {code}) ===", flush=True)
                print(path.read_text(), end="", flush=True)
    print("PACKAGE_DEMO_PASS: two subscribers, 40 custom messages each, checksum 23160, "
          "12 Rust-backed service responses, absent-service timeout, four clean exits", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, default=Path.cwd() / "package-logs")
    args = parser.parse_args()

    def interrupted(signum, _frame):
        raise RuntimeError(f"interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    run_demo(Path(__file__).resolve().parent, args.log_dir.resolve(), os.environ.get("ROS_DOMAIN_ID", "96"))


if __name__ == "__main__":
    main()
