import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class HomebrewInstallTests(unittest.TestCase):
    def fixture(self, directory):
        base = Path(directory)
        commands = base / "commands"
        commands.mkdir()
        repository = base / "brew-repo"
        repository.mkdir()
        log = base / "calls.jsonl"
        brew = commands / "brew"
        brew.write_text('#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\n'
                        'base=Path(os.environ["TEST_BREW_REPO"])\n'
                        'with open(os.environ["TEST_BREW_LOG"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                        'assert os.environ["HOMEBREW_NO_AUTO_UPDATE"]=="1"\n'
                        'if sys.argv[1:]==["--repository"]: print(base)\n'
                        'elif sys.argv[1:]==["tap-new","--no-git","local/rex-annotation"]: (base/"Library/Taps/local/homebrew-rex-annotation").mkdir(parents=True)\n'
                        'elif sys.argv[1:]==["install","--formula","local/rex-annotation/rex-annotation"]: pass\n'
                        'else: sys.exit(9)\n')
        brew.chmod(0o755)
        environment = {**os.environ, "PATH":str(commands) + os.pathsep + os.environ["PATH"],
                       "TEST_BREW_REPO":str(repository), "TEST_BREW_LOG":str(log), "PYTHONDONTWRITEBYTECODE":"1"}
        return base, repository, log, environment

    def test_local_install_uses_owned_tap_and_real_generated_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            base, repository, log, environment = self.fixture(directory)
            result = subprocess.run([sys.executable,str(ROOT / "scripts/install-homebrew"),"--output",str(base/"output")],
                                    env=environment,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls,[ ["--repository"], ["tap-new","--no-git","local/rex-annotation"],
                                     ["install","--formula","local/rex-annotation/rex-annotation"] ])
            formula = repository/"Library/Taps/local/homebrew-rex-annotation/Formula/rex-annotation.rb"
            version=json.loads((ROOT/"package.json").read_text())["version"]
            self.assertIn((base/("output/rex-annotation-"+version+".tar.gz")).as_uri(),formula.read_text())
            self.assertTrue((formula.parent.parent/".rex-annotation-local").exists())

    def test_prepare_only_never_invokes_brew(self):
        with tempfile.TemporaryDirectory() as directory:
            base, _, log, environment = self.fixture(directory)
            result = subprocess.run([sys.executable,str(ROOT/"scripts/install-homebrew"),"--prepare-only","--output",str(base/"output")],
                                    env=environment,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(log.exists())

    def test_unmanaged_existing_tap_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base, repository, log, environment = self.fixture(directory)
            tap=repository/"Library/Taps/local/homebrew-rex-annotation"
            tap.mkdir(parents=True)
            sentinel=tap/"README.md"
            sentinel.write_text("unrelated")
            result=subprocess.run([sys.executable,str(ROOT/"scripts/install-homebrew"),"--output",str(base/"output")],
                                  env=environment,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertIn("unowned tap",result.stderr)
            self.assertEqual(sentinel.read_text(),"unrelated")
            self.assertNotIn("install",log.read_text())


if __name__=="__main__":
    unittest.main()
