#!/usr/bin/env python3
"""Measure a whole command (including its persistent-server work), not CPU time."""
import json
import pathlib
import subprocess
import sys
import time

output = pathlib.Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
start = time.perf_counter()
result = subprocess.run(sys.argv[2:], check=False)
output.write_text(json.dumps({"wall_seconds": time.perf_counter() - start,
                              "exit_code": result.returncode}, indent=2) + "\n")
sys.exit(result.returncode)
