import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dustpilot import core  # noqa: E402


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, rel, size=10, fill=1, age_days=None):
        p = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(bytes([fill]) * size)
        if age_days is not None:
            t = time.time() - age_days * 86400
            os.utime(p, (t, t))
        return p

    def opts(self, **kw):
        base = dict(large_bytes=1_000_000, max_entries=100_000, stale_days=0, stale_min_bytes=0, duplicate_min_bytes=0)
        base.update(kw)
        return core.ScanOptions(**base)

    def names(self, res, cat):
        return {i.name for i in res.items if i.category == cat}

    def test_categories(self):
        for r in ("Caches/a.dat", "app.log", "x.tmp", "n.BAK", "keep.txt"):
            self.make(r)
        self.make("big.bin", size=2_000_000)
        res = core.scan(self.root, self.opts())
        self.assertEqual(self.names(res, core.CACHES), {"a.dat"})
        self.assertEqual(self.names(res, core.LOGS), {"app.log"})
        self.assertEqual(self.names(res, core.TEMP), {"x.tmp", "n.BAK"})
        self.assertEqual(self.names(res, core.LARGE), {"big.bin"})
        self.assertEqual(len(res.items), 5)
        self.assertEqual(res.files_checked, 6)

    def test_nested_cache_folder(self):
        self.make("Cache/sub/deeper/f.dat")
        self.assertEqual(self.names(core.scan(self.root, self.opts()), core.CACHES), {"f.dat"})

    def test_chosen_root_named_cache_does_not_flag_everything(self):
        root = os.path.join(self.root, "Cache")
        os.makedirs(root)
        open(os.path.join(root, "plain.txt"), "wb").write(b"x")
        self.assertEqual(core.scan(root, self.opts()).items, [])

    @unittest.skipIf(sys.platform == "win32", "symlink creation needs privileges on Windows")
    def test_symlinks_and_hidden_skipped(self):
        real = self.make("real.log")
        os.symlink(real, os.path.join(self.root, "link.log"))
        self.make(".hidden.log")
        self.assertEqual(self.names(core.scan(self.root, self.opts()), core.LOGS), {"real.log"})

    def test_entry_cap_reports_truncation(self):
        for i in range(20):
            self.make(f"f{i}.log")
        res = core.scan(self.root, self.opts(max_entries=5))
        self.assertTrue(res.truncated)
        self.assertLessEqual(len(res.items), 5)

    def test_cancellation(self):
        for i in range(5):
            self.make(f"f{i}.log")
        self.assertTrue(core.scan(self.root, self.opts(), lambda: True).cancelled)

    def test_old_files(self):
        self.make("old.dat", age_days=400)
        self.make("new.dat", age_days=5)
        self.assertEqual(self.names(core.scan(self.root, self.opts(stale_days=365)), core.OLD), {"old.dat"})

    def test_duplicates_keep_oldest(self):
        self.make("a/orig.bin", 2048, 7, age_days=30)
        self.make("b/copy.bin", 2048, 7, age_days=1)
        self.make("c/diff.bin", 2048, 8)
        self.make("d/small.bin", 10, 7)
        res = core.scan(self.root, self.opts(duplicate_min_bytes=1024))
        self.assertEqual(self.names(res, core.DUPES), {"copy.bin"})

    def test_same_size_different_content_not_duplicate(self):
        self.make("a.bin", 4096, 1)
        self.make("b.bin", 4096, 2)
        self.assertEqual(self.names(core.scan(self.root, self.opts(duplicate_min_bytes=1024)), core.DUPES), set())

    def test_scan_never_modifies_files(self):
        p = self.make("x.log")
        before = open(p, "rb").read(), os.stat(p).st_mtime
        core.scan(self.root, self.opts(duplicate_min_bytes=1))
        self.assertEqual((open(p, "rb").read(), os.stat(p).st_mtime), before)

    def item(self, name, cat, size=1):
        return core.Item(os.path.join(self.root, name), cat, size, None, "")

    def test_filter_and_search(self):
        items = [self.item("a.log", core.LOGS), self.item("b.tmp", core.TEMP), self.item("Report.log", core.LOGS)]
        self.assertEqual(len(core.visible(items, core.LOGS)), 2)
        self.assertEqual(len(core.visible(items, core.ALL_ITEMS, "report")), 1)

    def test_nothing_preselected_and_targets_are_selected_and_visible(self):
        items = [self.item("a.log", core.LOGS), self.item("b.tmp", core.TEMP)]
        self.assertEqual(core.trash_targets(items, set()), [])
        everything = {i.id for i in items}
        t = core.trash_targets(items, everything, core.LOGS)
        self.assertEqual([i.name for i in t], ["a.log"], "a filtered-out item must never be removed")

    def test_sorting(self):
        items = [self.item("b", core.LOGS, 5), self.item("a", core.LOGS, 50)]
        self.assertEqual([i.name for i in core.sort_items(items, "Size")], ["a", "b"])
        self.assertEqual([i.name for i in core.sort_items(items, "Name")], ["a", "b"])

    def test_csv_escaping_and_formula_guard(self):
        it = core.Item("/tmp/=evil \"x\".log", core.LOGS, 3, None, "a, b")
        out = core.to_csv([it])
        self.assertTrue(out.startswith('"Name","Category","Bytes","Modified","Path","Reason"\n'))
        self.assertIn("\"'=evil \"\"x\"\".log\"", out)
        self.assertIn('"a, b"', out)

    def test_trash_continues_after_failure(self):
        items = [self.item("a", core.LOGS), self.item("bad", core.LOGS), self.item("c", core.LOGS)]

        def fake(path):
            if os.path.basename(path) == "bad":
                raise OSError("denied")
        out = core.trash_items(items, fake)
        self.assertEqual(len(out.moved_ids), 2)
        self.assertEqual(out.failures, ["bad: denied"])

    def test_recycle_bin_refuses_off_windows(self):
        from dustpilot.recycle import send_to_recycle_bin
        if sys.platform != "win32":
            with self.assertRaises(OSError):
                send_to_recycle_bin(__file__)

    def test_format_bytes(self):
        self.assertEqual(core.format_bytes(0), "0 B")
        self.assertEqual(core.format_bytes(1536), "1.5 KB")


if __name__ == "__main__":
    unittest.main()
