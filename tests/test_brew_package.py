import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("brew_package", ROOT / "scripts/brew-package.py")
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class BrewPackageTests(unittest.TestCase):
    def test_archive_is_reproducible_and_contains_root_plugins_without_git_or_state(self):
        with tempfile.TemporaryDirectory(prefix="rex brew package ") as directory:
            output = Path(directory)
            archive, formula, first_hash = PACKAGE.build(output)
            before = archive.read_bytes()
            archive, formula, second_hash = PACKAGE.build(output)
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(before, archive.read_bytes())
            self.assertEqual(first_hash, hashlib.sha256(before).hexdigest())
            with tarfile.open(archive) as tar:
                names = tar.getnames()
            version = json.loads((ROOT / "package.json").read_text())["version"]
            prefix = "rex-annotation-" + version + "/"
            for name in ("LICENSE", "CHANGELOG.md", ".claude-plugin/plugin.json", "hooks/hooks.json", "integrations/pi/extensions/index.js", "bin/rex-annotation"):
                self.assertIn(prefix + name, names)
            self.assertTrue(all("/.git/" not in name and "__pycache__" not in name and "/dist/" not in name for name in names))
            body = formula.read_text()
            self.assertIn(archive.as_uri(), body)
            self.assertIn(first_hash, body)
            self.assertIn('#{opt_libexec}', body)
            self.assertNotIn("post_install", body)
            self.assertIn('license "MIT"', body)
            public_url=f'https://github.com/arrokh/rex-annotation/releases/download/v{version}/rex-annotation-{version}.tar.gz'
            public=PACKAGE.formula_for(archive,first_hash,version,public_url)
            self.assertIn(public_url,public)
            self.assertIn(first_hash,public)
            ruby = shutil.which("ruby")
            if ruby:
                result = subprocess.run([ruby, "-c", str(formula)], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_release_archive_honors_gitignore_inside_resource_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'repo'
            root.mkdir()
            subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
            (root/'.gitignore').write_text('.env*\n*.log\n')
            (root/'package.json').write_text('{"version":"0.1.0"}')
            resources=root/'integrations'
            resources.mkdir()
            (resources/'bridge.js').write_text('// shipped source\n')
            (resources/'.env.local').write_text('PRIVATE_FIXTURE=not-a-real-secret\n')
            (resources/'debug.log').write_text('private fixture\n')
            with mock.patch.object(PACKAGE,'ROOT',root):
                archive,_,_=PACKAGE.build(Path(directory)/'out')
            with tarfile.open(archive) as tar:
                names=tar.getnames()
            self.assertIn('rex-annotation-0.1.0/integrations/bridge.js',names)
            self.assertFalse(any('.env' in name or name.endswith('.log') for name in names))


if __name__ == "__main__":
    unittest.main()
