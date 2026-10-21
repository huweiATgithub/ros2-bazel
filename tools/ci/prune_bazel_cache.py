#!/usr/bin/env python3
"""Bound a quiescent Bazel 9 CI cache before archiving it (standard library only).

Run only after `bazel shutdown`, with no other process using these dedicated
cache directories. This is not a collector for shared/live developer caches.
Repository entries must remain whole; disk AC/CAS files may be evicted
independently because Bazel validates referenced CAS blobs on cache reads.
"""

import argparse
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import shutil
import stat


GIB = 1024 ** 3


def checked_root(path):
    """Reject symlink roots/ancestors, including links to missing targets."""
    root = Path(os.path.abspath(path))
    if root == Path(root.anchor):
        raise ValueError("Refusing to prune a filesystem root")
    for part in (*reversed(root.parents), root):
        if part.is_symlink():
            raise ValueError(f"Cache path must not traverse a symlink: {part}")
    if root.exists() and not root.is_dir():
        raise ValueError(f"Cache root is not a directory: {root}")
    return root


def nodes(path):
    """Walk without following symlinks, and refuse unexpected special files."""
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)):
        raise ValueError(f"Unsupported cache file type: {path}")
    yield path, info
    if stat.S_ISDIR(info.st_mode):
        for child in sorted(path.iterdir()):
            yield from nodes(child)


def accounted_bytes(info):
    # Conservative for both sparse files and many small files. Count every hard
    # link separately, directory metadata and symlink text, never link targets.
    return max(info.st_size, getattr(info, "st_blocks", 0) * 512)


def tree_bytes(path):
    return sum(accounted_bytes(info) for _, info in nodes(path))


@dataclass(frozen=True)
class Entry:
    path: Path
    size: int
    mtime_ns: int


def entry(path, mtime_ns=None):
    return Entry(path, tree_bytes(path), path.lstat().st_mtime_ns
                 if mtime_ns is None else mtime_ns)


def is_directory(path):
    return stat.S_ISDIR(path.lstat().st_mode)


def repository_entries(root):
    for child in sorted(root.iterdir()):
        if child.name == "content_addressable" and is_directory(child):
            for algorithm in sorted(child.iterdir()):
                if not is_directory(algorithm):
                    yield entry(algorithm)
                    continue
                for digest in sorted(algorithm.iterdir()):
                    cached_file = digest / "file"
                    # A download hit touches `file`, not its parent directory.
                    mtime = (cached_file.lstat().st_mtime_ns
                             if is_directory(digest) and not cached_file.is_symlink()
                             and cached_file.exists() else 0)
                    yield entry(digest, mtime)
        elif child.name == "contents" and is_directory(child):
            for inputs_hash in sorted(child.iterdir()):
                # Evict the complete hash directory, including all UUID trees
                # and their .recorded_inputs markers. Never edit a cached repo.
                markers = (list(inputs_hash.glob("*.recorded_inputs"))
                           if is_directory(inputs_hash) else [])
                mtime = max((p.lstat().st_mtime_ns for p in markers), default=0)
                yield entry(inputs_hash, mtime)
        else:
            # Unknown future layout: preserve or evict the whole subtree.
            yield entry(child)


def disk_entries(root):
    # Mirrors Bazel's GC order: oldest mtime first, relative path breaks ties
    # (AC precedes CAS). Include abandoned tmp/gc data after shutdown as well.
    for path, info in nodes(root):
        if not stat.S_ISDIR(info.st_mode):
            yield Entry(path, accounted_bytes(info), info.st_mtime_ns)


def remove_entry(path):
    if is_directory(path):
        shutil.rmtree(path)
    else:
        path.unlink()


def remove_empty_directories(root, kind):
    if kind == "disk":
        directories = [path for path, info in nodes(root)
                       if stat.S_ISDIR(info.st_mode)]
    else:
        # Empty directories inside a retained fetched repository can be
        # meaningful. Only tidy cache layout directories, never repo contents.
        directories = [root]
        for name in ("contents", "content_addressable"):
            path = root / name
            if path.exists() and not path.is_symlink() and is_directory(path):
                directories.append(path)
                if name == "content_addressable":
                    directories.extend(p for p in path.iterdir() if is_directory(p))
    for path in sorted(directories, key=lambda p: (-len(p.parts), str(p))):
        try:
            path.rmdir()
        except OSError as error:
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise


def prune_cache(path, kind, limit):
    if limit < 0:
        raise ValueError("Cache limit cannot be negative")
    if kind not in ("repository", "disk"):
        raise ValueError(f"Unknown cache kind: {kind}")
    root = checked_root(path)
    result = {"cache": kind, "limit_bytes": limit, "before_bytes": 0,
              "after_bytes": 0, "removed_entries": 0}
    if not root.exists():
        return result
    before = tree_bytes(root)
    result["before_bytes"] = before
    candidates = sorted(
        repository_entries(root) if kind == "repository" else disk_entries(root),
        # Drop an oversized entry first rather than evicting all smaller ones
        # only to discover that the newest entry cannot fit by itself.
        key=lambda item: (item.size <= limit, item.mtime_ns,
                          item.path.relative_to(root).as_posix()))
    remaining = before
    index = 0
    while remaining > limit:
        while remaining > limit and index < len(candidates):
            candidate = candidates[index]
            remove_entry(candidate.path)
            remaining -= candidate.size
            result["removed_entries"] += 1
            index += 1
        # Directory blocks can shrink or stay allocated after deletion. Recheck
        # the actual tree, not just the estimate, before claiming the bound.
        remove_empty_directories(root, kind)
        remaining = tree_bytes(root) if root.exists() else 0
        if remaining > limit and index == len(candidates):
            raise RuntimeError(f"Could not bound {root}: {remaining} > {limit}")
    result["after_bytes"] = remaining
    return result


def nonnegative_integer(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--repository-max-bytes", type=nonnegative_integer,
                        default=4 * GIB)
    parser.add_argument("--disk-max-bytes", type=nonnegative_integer,
                        default=2 * GIB)
    args = parser.parse_args()
    # Validate both roots before making any changes.
    root = checked_root(args.cache_root)
    for name in ("repository", "disk"):
        checked_root(root / name)
    results = [prune_cache(root / "repository", "repository",
                           args.repository_max_bytes),
               prune_cache(root / "disk", "disk", args.disk_max_bytes)]
    print(json.dumps({"caches": results,
                      "total_after_bytes": sum(r["after_bytes"] for r in results)},
                     indent=2))


if __name__ == "__main__":
    main()
