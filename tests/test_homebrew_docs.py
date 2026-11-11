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

    def run_example(self, script, *, failure=None, answer="y\n"):
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
                                    input=answer, text=True, capture_output=True, timeout=5)
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def migration(self):
        return self.code_block("docs/homebrew.md", "## Migrate from the old tap")

    def test_migration_stops_at_each_failed_command(self):
        expected = [
            ["brew", "tap", TAP, "https://github.com/arrokh/rex-annotation"],
            ["brew", "reinstall", FORMULA],
            ["brew", "test", FORMULA],
            ["brew", "cleanup", "--dry-run", FORMULA],
            ["brew", "cleanup", FORMULA],
            ["brew", "untap", "arrokh/tap"],
            ["rex-annotation", "status"],
        ]
        for index, failed in enumerate(expected):
            with self.subTest(command=failed):
                result, calls = self.run_example(self.migration(), failure=failed)
                self.assertEqual(calls, expected[:index + 1])
                self.assertEqual(result.returncode, 42)

    def test_migration_requires_explicit_confirmation_after_dry_run(self):
        for answer in ("n\n", "\n", ""):
            with self.subTest(answer=answer):
                _, calls = self.run_example(self.migration(), answer=answer)
                self.assertEqual(len(calls), 4)
                self.assertEqual(calls[-1], ["brew", "cleanup", "--dry-run", FORMULA])
        result, calls = self.run_example(self.migration())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[-3:], [["brew", "cleanup", FORMULA],
                                     ["brew", "untap", "arrokh/tap"], ["rex-annotation", "status"]])

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
