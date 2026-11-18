import tempfile
import unittest
from pathlib import Path
from server.scop_core.core import discover, match, permissions_for


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.skills = Path(self.tmp.name)

    def add(self, folder, name, description):
        path = self.skills / folder
        path.mkdir()
        (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n# Details\n", encoding="utf-8")

    def test_discover(self):
        self.add("pr", "pr-source-summary", "Summarize GitHub pull requests")
        self.assertEqual([s.name for s in discover(self.skills)], ["pr-source-summary"])

    def test_match(self):
        self.add("pr", "pr-source-summary", "Summarize GitHub pull requests")
        self.add("bug", "bug-regression-test", "Propose regression tests for software bugs")
        ranks = match("summarize pull requests", discover(self.skills))
        self.assertEqual(ranks[0][0].name, "pr-source-summary")

    def test_no_match_returns_empty(self):
        self.add("pr", "pr-source-summary", "Summarize GitHub pull requests")
        self.assertEqual(match("unrelated bananas", discover(self.skills)), [])

    def test_duplicate_name_rejected(self):
        self.add("a", "duplicate", "One")
        self.add("b", "duplicate", "Two")
        with self.assertRaises(ValueError):
            discover(self.skills)

    def test_missing_frontmatter_rejected(self):
        path = self.skills / "bad"
        path.mkdir()
        (path / "SKILL.md").write_text("# no metadata")
        with self.assertRaises(ValueError):
            discover(self.skills)

    def test_symlink_directory_ignored(self):
        self.add("ok", "skill-one", "description")
        try:
            (self.skills / "linked").symlink_to(self.skills / "ok", target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.assertEqual(len(discover(self.skills)), 1)

    def test_permission_only_definition_read(self):
        self.add("pr", "pr-source-summary", "PR summaries")
        self.assertEqual(permissions_for(discover(self.skills)[0]), ("local:read-skill-definition",))

    def test_unterminated_frontmatter_rejected(self):
        folder = self.skills / "broken"
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            "---\\nname: broken-skill\\ndescription: Missing closing delimiter\\n# content\\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "unterminated frontmatter"):
            discover(self.skills)

    def test_symlink_root_rejected(self):
        self.add("ok", "skill-one", "description")
        linked_root = self.skills.parent / "linked-root"
        try:
            linked_root.symlink_to(self.skills, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        self.addCleanup(lambda: linked_root.unlink(missing_ok=True))
        with self.assertRaisesRegex(ValueError, "symlinked skills root"):
            discover(linked_root)

    def test_stopword_only_input_has_no_match(self):
        self.add("pr", "pr-source-summary", "Summarize GitHub pull requests and a report")
        self.add("bug", "bug-regression-test", "Propose regression tests and a check")
        self.assertEqual(match("and a", discover(self.skills)), [])

    def test_empty_task_rejected(self):
        with self.assertRaises(ValueError):
            match("   ", [])


if __name__ == "__main__":
    unittest.main()
