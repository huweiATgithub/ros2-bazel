"""Regression tests for the isolated CI cache collector; no Bazel needed."""

import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from prune_bazel_cache import GIB, prune_cache, tree_bytes


class PruneCacheTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "cache"
        self.root.mkdir()

    def file(self, relative, size=8192, mtime=10):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        os.utime(path, ns=(mtime, mtime))
        return path

    def assert_bounded(self, result, limit):
        actual = tree_bytes(self.root) if self.root.exists() else 0
        self.assertEqual(result["after_bytes"], actual)
        self.assertLessEqual(actual, limit)

    def test_missing_directory_is_empty(self):
        self.root.rmdir()
        result = prune_cache(self.root, "disk", 0)
        self.assertEqual(result["before_bytes"], 0)
        self.assert_bounded(result, 0)
        self.assertFalse(self.root.exists())

    def test_under_limit_is_unchanged_and_idempotent(self):
        blob = self.file("cas/aa/digest")
        before = tree_bytes(self.root)
        first = prune_cache(self.root, "disk", before)
        second = prune_cache(self.root, "disk", before)
        self.assertEqual(first, second)
        self.assertEqual(first["removed_entries"], 0)
        self.assertEqual(blob.read_bytes(), b"x" * 8192)
        self.assert_bounded(first, before)

    def test_disk_evicts_oldest_and_ac_before_cas_on_tie(self):
        old = self.file("sha256/ac/aa/old", mtime=1)
        cas = self.file("sha256/cas/aa/referenced", mtime=1)
        new = self.file("sha256/ac/bb/new", mtime=2)
        limit = tree_bytes(self.root) - tree_bytes(old)
        result = prune_cache(self.root, "disk", limit)
        self.assertFalse(old.exists())
        self.assertTrue(cas.exists())
        self.assertTrue(new.exists())
        self.assertEqual(result["removed_entries"], 1)
        self.assert_bounded(result, limit)

    def test_oversized_newest_blob_does_not_evict_small_old_blob(self):
        small = self.file("cas/aa/small", mtime=1)
        large = self.file("cas/bb/huge", size=128 * 1024, mtime=100)
        limit = tree_bytes(self.root) - tree_bytes(large)
        result = prune_cache(self.root, "disk", limit)
        self.assertFalse(large.exists())
        self.assertTrue(small.exists())
        self.assert_bounded(result, limit)

    def test_zero_budget_removes_everything_including_directory_overhead(self):
        self.file("cas/aa/file")
        (self.root / "empty/nested").mkdir(parents=True)
        result = prune_cache(self.root, "disk", 0)
        self.assert_bounded(result, 0)
        self.assertFalse(self.root.exists())

    def test_repository_download_markers_are_evicted_together(self):
        old = self.file("content_addressable/sha256/old/file", mtime=1)
        self.file("content_addressable/sha256/old/id-canonical", size=0)
        self.file("content_addressable/sha256/new/file", mtime=100)
        old_dir = old.parent
        limit = tree_bytes(self.root) - tree_bytes(old_dir)
        result = prune_cache(self.root, "repository", limit)
        self.assertFalse(old_dir.exists())
        self.assertTrue((self.root / "content_addressable/sha256/new/file").exists())
        self.assert_bounded(result, limit)

    def test_repository_contents_use_markers_and_preserve_whole_hash(self):
        self.file("contents/old/uuid/lib.so", mtime=1000)
        self.file("contents/old/uuid.recorded_inputs", size=0, mtime=1)
        self.file("contents/new/uuid1/lib.so", mtime=0)
        self.file("contents/new/uuid1.recorded_inputs", size=0, mtime=0)
        self.file("contents/new/uuid2/lib.so", mtime=0)
        self.file("contents/new/uuid2.recorded_inputs", size=0, mtime=100)
        (self.root / "contents/new/uuid2/meaningful-empty-directory").mkdir()
        limit = tree_bytes(self.root) - tree_bytes(self.root / "contents/old")
        result = prune_cache(self.root, "repository", limit)
        self.assertFalse((self.root / "contents/old").exists())
        for name in ("uuid1/lib.so", "uuid1.recorded_inputs", "uuid2/lib.so",
                     "uuid2.recorded_inputs", "uuid2/meaningful-empty-directory"):
            self.assertTrue((self.root / "contents/new" / name).exists())
        self.assert_bounded(result, limit)

    def test_oversized_repository_entry_is_removed_whole(self):
        self.file("contents/giant/uuid/big", size=128 * 1024)
        self.file("contents/giant/uuid.recorded_inputs", size=0)
        result = prune_cache(self.root, "repository", 64 * 1024)
        self.assertFalse((self.root / "contents/giant").exists())
        self.assert_bounded(result, 64 * 1024)

    def test_symlinks_inside_repository_never_touch_targets(self):
        outside = self.base / "outside"
        outside.mkdir()
        important = outside / "keep"
        important.write_text("must survive")
        self.file("contents/hash/uuid.recorded_inputs", size=0)
        tree = self.root / "contents/hash/uuid"
        tree.mkdir()
        (tree / "escape").symlink_to(outside, target_is_directory=True)
        (self.root / "content_addressable").symlink_to(outside, target_is_directory=True)
        result = prune_cache(self.root, "repository", 0)
        self.assertEqual(important.read_text(), "must survive")
        self.assert_bounded(result, 0)

    def test_disk_symlink_and_broken_link_are_counted_without_following(self):
        outside = self.base / "outside"
        outside.write_text("must survive")
        (self.root / "escape").symlink_to(outside)
        (self.root / "broken").symlink_to(self.base / "missing")
        result = prune_cache(self.root, "disk", 0)
        self.assertEqual(outside.read_text(), "must survive")
        self.assert_bounded(result, 0)

    def test_root_or_ancestor_symlink_is_rejected(self):
        link = self.base / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        for root in (link, link / "nested"):
            with self.subTest(root=root), self.assertRaises(ValueError):
                prune_cache(root, "disk", 0)
        self.assertTrue(self.root.exists())

    def test_sparse_files_and_hardlinks_are_conservatively_counted(self):
        sparse = self.root / "sparse"
        with sparse.open("wb") as stream:
            stream.truncate(128 * 1024)
        os.link(sparse, self.root / "hardlink")
        self.assertGreaterEqual(tree_bytes(self.root), 2 * 128 * 1024)
        result = prune_cache(self.root, "disk", 64 * 1024)
        self.assert_bounded(result, 64 * 1024)

    def test_special_file_fails_closed(self):
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(ValueError):
            prune_cache(self.root, "disk", 0)
        self.assertTrue((self.root / "pipe").exists())

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            prune_cache(self.root, "disk", -1)
        with self.assertRaises(ValueError):
            prune_cache(self.root, "typo", 0)
        with self.assertRaises(ValueError):
            prune_cache(Path("/"), "disk", 0)

    def test_ci_shell_does_not_mask_pruning_failure_with_tee(self):
        script = Path(__file__).with_name("prune_bazel_cache.py")
        (self.root / "repository").symlink_to(self.base / "missing")
        command = (f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
                   f"--cache-root {shlex.quote(str(self.root))} | tee /dev/null")
        process = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", command],
                                 capture_output=True, text=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("symlink", process.stderr)

    def test_cli_default_gib_limits_on_oversized_sparse_entries(self):
        for name, size in (("repository/content_addressable/sha256/huge/file", 5 * GIB),
                           ("disk/cas/aa/huge", 3 * GIB)):
            path = self.root / name
            path.parent.mkdir(parents=True)
            with path.open("wb") as stream:
                stream.truncate(size)
        script = Path(__file__).with_name("prune_bazel_cache.py")
        process = subprocess.run(
            [sys.executable, str(script), "--cache-root", str(self.root)],
            capture_output=True, text=True, check=True)
        result = json.loads(process.stdout)
        self.assertEqual([c["limit_bytes"] for c in result["caches"]],
                         [4 * GIB, 2 * GIB])
        for cache in result["caches"]:
            self.assertGreater(cache["before_bytes"], cache["limit_bytes"])
            self.assertLessEqual(cache["after_bytes"], cache["limit_bytes"])
        self.assertLessEqual(result["total_after_bytes"], 6 * GIB)

    def test_cli_bounds_both_caches_and_emits_json(self):
        self.file("repository/content_addressable/sha256/hash/file", size=128 * 1024)
        self.file("disk/cas/aa/hash", size=128 * 1024)
        script = Path(__file__).with_name("prune_bazel_cache.py")
        process = subprocess.run(
            [sys.executable, str(script), "--cache-root", str(self.root),
             "--repository-max-bytes", "65536", "--disk-max-bytes", "65536"],
            capture_output=True, text=True, check=True)
        result = json.loads(process.stdout)
        self.assertEqual(len(result["caches"]), 2)
        for cache in result["caches"]:
            self.assertLessEqual(cache["after_bytes"], 65536)
            self.assertGreater(cache["before_bytes"], 65536)
        self.assertLessEqual(result["total_after_bytes"], 131072)


if __name__ == "__main__":
    unittest.main()
