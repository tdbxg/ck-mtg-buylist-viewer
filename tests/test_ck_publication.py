import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PublicationTests(unittest.TestCase):
    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, repo, filename, content):
        (repo / filename).write_text(content)
        self.git(repo, "add", filename)
        self.git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-m", filename)

    def scenario(self, conflict=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, ck, other = (root / name for name in ("remote.git", "ck", "other"))
            subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)],
                           check=True, capture_output=True)
            self.git(root, "clone", str(remote), str(ck))
            self.git(ck, "config", "user.name", "Test")
            self.git(ck, "config", "user.email", "test@example.invalid")
            self.commit(ck, "data.txt", "baseline\n")
            self.git(ck, "push", "origin", "main")
            self.git(root, "clone", str(remote), str(other))
            self.commit(ck, "data.txt", "fresh CK sample\n")
            self.commit(other, "data.txt" if conflict else "ui.txt", "other writer\n")
            self.git(other, "push", "origin", "main")
            before = self.git(other, "rev-parse", "HEAD")
            result = subprocess.run([sys.executable, str(ROOT / "scripts/publish_snapshot.py")],
                                    cwd=ck, capture_output=True, text=True)
            self.git(other, "fetch", "origin")
            if conflict:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Publication conflict", result.stdout + result.stderr)
                self.assertEqual(self.git(other, "rev-parse", "origin/main"), before)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.git(other, "show", "origin/main:data.txt"), "fresh CK sample")
                self.assertEqual(self.git(other, "show", "origin/main:ui.txt"), "other writer")

    def test_advanced_remote_keeps_new_sample_and_other_writer(self):
        self.scenario()

    def test_overlapping_data_conflict_never_overwrites_remote(self):
        self.scenario(conflict=True)

    def test_queued_workflow_checks_out_latest_main(self):
        workflow = (ROOT / ".github/workflows/update-buylist.yml").read_text()
        self.assertIn("ref: main", workflow)


if __name__ == "__main__":
    unittest.main()
