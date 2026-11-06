import tempfile
import unittest
from pathlib import Path

from app.runtime.runner import prepare_jobdir


class JobdirModeTests(unittest.TestCase):
    def test_prepare_jobdir_clears_existing_state_for_fresh_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jobdir = Path(tmpdir) / "run_state" / "example"
            jobdir.mkdir(parents=True)
            (jobdir / "requests.queue").write_text("stale", encoding="utf-8")
            (jobdir / "seen.txt").write_text("old", encoding="utf-8")

            prepare_jobdir(jobdir, fresh=True, root=tmpdir)

            self.assertTrue(jobdir.exists())
            self.assertEqual([], sorted(p.name for p in jobdir.iterdir()))

    def test_prepare_jobdir_rejects_absolute_path_outside_run_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            marker = outside / "keep.txt"
            marker.write_text("do not delete", encoding="utf-8")

            with self.assertRaises(ValueError):
                prepare_jobdir(outside, fresh=True, root=tmpdir)

            self.assertTrue(marker.exists())

    def test_prepare_jobdir_rejects_parent_traversal_outside_run_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dangerous = Path("run_state") / ".." / "outside"

            with self.assertRaises(ValueError):
                prepare_jobdir(dangerous, fresh=True, root=tmpdir)

            self.assertFalse((Path(tmpdir) / "outside").exists())

    def test_prepare_jobdir_rejects_run_state_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_state = Path(tmpdir) / "run_state"
            run_state.mkdir()
            marker = run_state / "keep.txt"
            marker.write_text("do not delete all state", encoding="utf-8")

            with self.assertRaises(ValueError):
                prepare_jobdir(run_state, fresh=True, root=tmpdir)

            self.assertTrue(marker.exists())
