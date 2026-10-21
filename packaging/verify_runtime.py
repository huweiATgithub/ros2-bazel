#!/usr/bin/env python3
"""Audit an extracted Ubuntu 24.04 x86_64 package, without Bazel or ROS."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


# These are platform ABI requirements, not libraries silently supplied by an
# installed ROS distribution. Other libraries must resolve inside the package.
SYSTEM_LIBRARIES = {
    "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1",
    "libgcc_s.so.1", "libstdc++.so.6", "ld-linux-x86-64.so.2",
}


def command(*args):
    result = subprocess.run(
        args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=True, timeout=15, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    return result.stdout


def validate_linkage(root, program, dynamic, dependencies):
    interpreters = re.findall(r"Requesting program interpreter: ([^\]]+)\]", program)
    if len(interpreters) != 1:
        raise RuntimeError("expected one Linux dynamic interpreter")
    loader = Path(interpreters[0])
    resolved_loader = loader.resolve()
    if (loader.name != "ld-linux-x86-64.so.2" or not loader.is_file()
            or not any(resolved_loader.is_relative_to(base) for base in ("/lib", "/usr/lib"))):
        raise RuntimeError(f"unexpected ELF interpreter: {loader}")
    for needed in re.findall(r"\(NEEDED\).*\[([^\]]+)\]", dynamic):
        if "/" in needed:
            raise RuntimeError(f"nonrelocatable DT_NEEDED path: {needed}")
    if "not found" in dependencies:
        raise RuntimeError(f"unresolved runtime dependency:\n{dependencies}")
    for line in dependencies.splitlines():
        match = re.match(r"\s*(\S+)\s+=>\s+(/\S+)", line)
        if match:
            soname, resolved = match.groups()
            resolved = Path(resolved).resolve()
            if not resolved.is_relative_to(root):
                system_path = any(resolved.is_relative_to(base) for base in ("/lib", "/usr/lib"))
                if soname not in SYSTEM_LIBRARIES or not system_path:
                    raise RuntimeError(f"undeclared external runtime library: {line.strip()}")
        else:
            # ldd emits the loader, and libraries lacking a SONAME, directly
            # as /absolute/path (address), without the usual 'name => path'.
            direct = re.match(r"\s*(/\S+)\s+\(", line)
            if direct:
                resolved = Path(direct.group(1)).resolve()
                if resolved != resolved_loader and not resolved.is_relative_to(root):
                    raise RuntimeError(f"undeclared external runtime library: {line.strip()}")


def verify(root):
    root = root.resolve()
    manifest = json.loads((root / "runtime.json").read_text())
    inventory = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            if os.path.isabs(os.readlink(path)) or not path.resolve().is_relative_to(root) or not path.exists():
                raise RuntimeError(f"broken or nonrelocatable symlink: {relative}")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            inventory[relative] = digest.hexdigest()

    elf_reports = {}
    for relative in manifest["executables"]:
        executable = root / relative
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError(f"missing executable permission: {relative}")
        runfiles = Path(str(executable) + ".runfiles")
        if not runfiles.is_dir() or not any(runfiles.rglob("*")):
            raise RuntimeError(f"missing declared runfiles: {relative}")
        header = command("readelf", "-hW", str(executable))
        if "Advanced Micro Devices X86-64" not in header:
            raise RuntimeError(f"not an x86_64 ELF executable: {relative}")
        program = command("readelf", "-lW", str(executable))
        dynamic = command("readelf", "-dW", str(executable))
        # Inspect actual ELF metadata. --dynamic_mode=off is not full static
        # linkage and we deliberately do not copy glibc/the host loader.
        dependencies = command("ldd", str(executable))
        validate_linkage(root, program, dynamic, dependencies)
        elf_reports[relative] = {
            "interpreter": [line.strip() for line in program.splitlines() if "interpreter" in line],
            "dynamic_tags": [line.strip() for line in dynamic.splitlines()
                             if any(tag in line for tag in ("NEEDED", "RPATH", "RUNPATH"))],
            "ldd": dependencies.splitlines(),
        }
    return {"platform": manifest["tested_platform"], "sha256": inventory, "elf": elf_reports}


if __name__ == "__main__":
    print(json.dumps(verify(Path(__file__).resolve().parent), indent=2))
