"""Test Agent Skill ownership, updates and removal without opening a vault."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).absolute().parents[1]
NAME = "use-bitwarden-window"


class AgentSkillTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "test home"
        self.home.mkdir()
        self.pkg = Path(tmp.name) / "package"
        (self.pkg / "lib").mkdir(parents=True)
        self.helper = self.pkg / "lib/agent-skill.py"
        shutil.copy2(ROOT / "lib/agent-skill.py", self.helper)
        shutil.copytree(ROOT / "skills", self.pkg / "skills")
        self.source = self.pkg / "skills" / NAME / "SKILL.md"
        self.codex = self.home / ".agents/skills" / NAME
        self.claude = self.home / ".claude/skills" / NAME

    def invoke(self, action):
        subprocess.run([sys.executable, "-I", self.helper, action], check=True,
                       env={"HOME": str(self.home)}, capture_output=True)

    def test_install_upgrade_remove_both(self):
        self.invoke("uninstall")
        self.invoke("install")
        guides = [d / "SKILL.md" for d in (self.codex, self.claude)]
        for guide in guides:
            self.assertEqual(guide.read_bytes(), self.source.read_bytes())
        original = guides[0].stat().st_ino
        self.invoke("install")
        self.assertEqual(guides[0].stat().st_ino, original)
        self.source.write_text("updated skill fixture\n")
        self.invoke("install")
        for guide in guides:
            self.assertEqual(guide.read_text(), self.source.read_text())
        extra = self.claude / "user.txt"
        extra.write_text("mine")
        self.invoke("uninstall")
        self.assertFalse(self.codex.exists())
        self.assertEqual(list(self.claude.iterdir()), [extra])

    def test_preserves_local_changes_independently(self):
        self.invoke("install")
        (self.codex / "SKILL.md").write_text("custom")
        self.source.write_text("updated")
        self.invoke("install")
        self.invoke("uninstall")
        self.assertEqual((self.codex / "SKILL.md").read_text(), "custom")
        self.assertFalse(self.claude.exists())

    def test_foreign_directory_and_dangling_symlink(self):
        self.codex.mkdir(parents=True)
        (self.codex / "SKILL.md").write_text("existing")
        self.claude.parent.mkdir(parents=True)
        dest = self.home / "absent"
        self.claude.symlink_to(dest)
        self.invoke("install")
        self.invoke("uninstall")
        self.assertEqual((self.codex / "SKILL.md").read_text(), "existing")
        self.assertEqual(self.claude.readlink(), dest)
        self.assertFalse(dest.exists())

    def test_skips_linked_registry_and_preserves_sibling(self):
        outside = self.home / "my-skills"
        outside.mkdir()
        self.codex.parent.parent.mkdir()
        self.codex.parent.symlink_to(outside)
        sibling = self.claude.parent / "bitwarden-window/SKILL.md"
        sibling.parent.mkdir(parents=True)
        sibling.write_text("my private skill")
        self.invoke("install")
        self.assertTrue((self.claude / "SKILL.md").exists())
        self.invoke("uninstall")
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(sibling.read_text(), "my private skill")

    def test_replaced_guide_link(self):
        self.invoke("install")
        guide = self.codex / "SKILL.md"
        guide.unlink()
        guide.symlink_to(self.source)
        self.invoke("uninstall")
        self.assertTrue(guide.is_symlink())
        self.assertTrue(self.source.exists())


if __name__ == "__main__":
    unittest.main()
