"""Adapt Bazel's runfiles paths and test XML destination to launch_testing."""
import os
import sys
from launch_testing.launch_test import main

if __name__ == "__main__":
    test_file, producer, observer, client = sys.argv[1:]
    for key, value in [("DEMO_PRODUCER", producer), ("DEMO_OBSERVER", observer), ("DEMO_CLIENT", client)]:
        os.environ[key] = os.path.abspath(value)
    arguments = [os.path.abspath(test_file)]
    if os.environ.get("XML_OUTPUT_FILE"):
        arguments += ["--junit-xml", os.environ["XML_OUTPUT_FILE"]]
    sys.argv = [sys.argv[0]] + arguments
    sys.exit(main())
