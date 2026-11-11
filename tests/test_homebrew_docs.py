import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
TAP = "arrokh/rex-annotation"
FORMULA = TAP + "/rex-annotation"


class HomebrewDocsTests(unittest.TestCase):
    def code_block(self, path, heading):
        section = (ROOT / path).read_text().split(heading + "\n", 1)[1].split("\n## ", 1)[0]
        return re.search(r"```sh\n(.*?)```", section, re.DOTALL).group(1)

    def run_example(self, script, *, failure=None):
        with tempfile.TemporaryDirectory(prefix="rex-brew-docs-") as directory:
            base = Path(directory)
            commands = base / "commands"
            commands.mkdir()
            log = base / "calls.jsonl"
            fake = (
                "#!" + sys.executable + "\nimport json,os,sys\nfrom pathlib import Path\n"
                "call=[Path(sys.argv[0]).name,*sys.argv[1:]]\n"
                "with open(os.environ['TEST_LOG'],'a') as stream:stream.write(json.dumps(call)+'\\n')\n"
                "sys.exit(42 if call==json.loads(os.environ['TEST_FAILURE']) else 0)\n"
            )
            for name in ("brew", "rex-annotation"):
                command = commands / name
                command.write_text(fake)
                command.chmod(0o755)
            example = base / "example.sh"
            example.write_text(script)
            environment = {"HOME": str(base), "PATH": str(commands), "TEST_LOG": str(log),
                           "TEST_FAILURE": json.dumps(failure), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run([shutil.which("bash"), str(example)], env=environment,
                                    input="", text=True, capture_output=True, timeout=5)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_public_docs_do_not_link_removed_old_tap_migration(self):
        for path in ("README.md", "docs/homebrew.md", "docs/setup.md", "docs/development.md"):
            text = (ROOT / path).read_text()
            with self.subTest(path=path):
                self.assertNotIn("migrate-from-the-old-tap", text)
                self.assertNotIn("arrokh/tap", text)

    def test_upgrade_example_stops_at_failed_brew_command(self):
        text = (ROOT / "docs/homebrew.md").read_text()
        script = re.findall(r"```sh\n(.*?)```", text, re.DOTALL)[1]
        commands = [["brew", "update"], ["brew", "upgrade", FORMULA],
                    ["rex-annotation", "install"], ["rex-annotation", "status"]]
        for index, failed in enumerate(commands):
            with self.subTest(command=failed):
                result, calls = self.run_example(script, failure=failed)
                self.assertEqual(result.returncode, 42)
                self.assertEqual(calls, commands[:index + 1])
        result, calls = self.run_example(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, commands)

    def test_release_title_convention_is_version_only(self):
        text = (ROOT / "docs/development.md").read_text()
        self.assertIn("--title vX.Y.Z", text)
        self.assertIn("title must exactly match the tag", text)

    def test_install_examples_do_not_run_setup_after_failed_brew(self):
        for path, heading in (("README.md", "## Install"), ("docs/setup.md", "## Homebrew"),
                              ("docs/homebrew.md", "## Install or upgrade")):
            script = self.code_block(path, heading)
            for failed in (["brew", "tap", TAP, "https://github.com/arrokh/rex-annotation"],
                           ["brew", "install", FORMULA]):
                with self.subTest(path=path, command=failed):
                    result, calls = self.run_example(script, failure=failed)
                    self.assertEqual(result.returncode, 42)
                    self.assertEqual(calls[-1], failed)
                    self.assertTrue(all(call[0] == "brew" for call in calls))


if __name__ == "__main__":
    unittest.main()
