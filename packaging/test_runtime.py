"""Host-side tests for package verification and bounded process orchestration."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("run_demo")
audit = load("verify_runtime")


class RuntimeTests(unittest.TestCase):
    def test_direct_absolute_dependency_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "undeclared external"):
                audit.validate_linkage(
                    Path(directory),
                    "[Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]",
                    "",
                    "/tmp/outside/libunexpected.so (0x00000000)",
                )

    def test_absolute_needed_path_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "nonrelocatable DT_NEEDED"):
                audit.validate_linkage(
                    Path(directory),
                    "[Requesting program interpreter: /lib64/ld-linux-x86-64.so.2]",
                    "0x0000000000000001 (NEEDED) Shared library: [/tmp/outside/libunexpected.so]",
                    "",
                )

    def test_nonplatform_interpreter_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "unexpected ELF interpreter"):
                audit.validate_linkage(
                    Path(directory),
                    "[Requesting program interpreter: /tmp/outside/ld-linux-x86-64.so.2]",
                    "", "",
                )

    def test_missing_output_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "app.log"
            log.write_text("prefix EXPECTED suffix\n")
            with self.assertRaises(RuntimeError):
                runner.require_line(log, "EXPECTED")

    def test_escaping_symlink_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime.json").write_text(json.dumps({"executables": []}))
            (root / "escape").symlink_to("/etc/os-release")
            with self.assertRaisesRegex(RuntimeError, "nonrelocatable symlink"):
                audit.verify(root)

    def test_missing_executable_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime.json").write_text(json.dumps({"executables": ["missing"]}))
            with self.assertRaisesRegex(RuntimeError, "missing executable"):
                audit.verify(root)

    def exercise_runner(self, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "published"
            for role in ("observer", "client", "producer"):
                path = root / "apps" / role / role
                path.parent.mkdir(parents=True)
                path.write_text("#!/usr/bin/python3\n" + f'''
import os, pathlib, signal, sys, time
assert "AMENT_PREFIX_PATH" not in os.environ
assert "PYTHONPATH" not in os.environ
assert "LD_LIBRARY_PATH" not in os.environ
assert os.environ["ROS_DOMAIN_ID"] == "97"
role = {role!r}
marker = pathlib.Path({str(marker)!r})
if role == "producer":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print("PUBLISHED 40", flush=True)
    for number in range(1, 13):
        print(f"SERVICE {{number}} {{35 if number % 2 else 425}}", flush=True)
    marker.touch()
    while True: time.sleep(0.05)
else:
    print("OBSERVER_READY" if role == "observer" else "ABSENT_SERVICE_TIMEOUT_OK", flush=True)
    while not marker.exists(): time.sleep(0.01)
    if role == "observer":
        print({("BROKEN" if corrupt else "RECEIVED 40 CHECKSUM 23160 CUSTOM_FIELDS_OK")!r}, flush=True)
    else:
        print("SERVICE_PASS 12", flush=True)
''')
                path.chmod(0o755)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                if corrupt:
                    with self.assertRaisesRegex(RuntimeError, "missing"):
                        runner.run_demo(root, root / "logs", "97")
                else:
                    runner.run_demo(root, root / "logs", "97")
            return output.getvalue()

    def test_success_requires_all_outputs_and_clean_exits(self):
        output = self.exercise_runner()
        self.assertIn("PACKAGE_DEMO_PASS:", output)
        self.assertEqual(output.count("(exit 0)"), 4)

    def test_corrupt_output_fails_and_cleans_up(self):
        output = self.exercise_runner(corrupt=True)
        self.assertNotIn("PACKAGE_DEMO_PASS:", output)
        self.assertIn("=== producer (exit 0) ===", output)


if __name__ == "__main__":
    unittest.main()
