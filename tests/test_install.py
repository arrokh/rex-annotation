import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("local_install", ROOT / "scripts/install.py")
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class InstallerTests(unittest.TestCase):
    def run_install(self, home, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts/install.py"), *args],
                              env={**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                                   "CODEX_HOME": str(home / ".codex"), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=5)

    def test_rex_install_is_idempotent_and_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".config/rex"
            config.mkdir(parents=True)
            init = config / "init.lua"
            init.write_text('require("unrelated")\n')
            first = self.run_install(home, "--rex")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self.run_install(home, "--rex")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(init.read_text().startswith('require("unrelated")\n'))
            self.assertEqual(init.read_text().count('require("rex-annotation")'), 1)
            self.assertIn(str(ROOT / "rex/annotate.lua"), (config / "rex-annotation.lua").read_text())

    def test_unrelated_loader_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".config/rex"
            config.mkdir(parents=True)
            (config / "rex-annotation.lua").write_text("-- user's file\n")
            result = self.run_install(home, "--rex")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((config / "rex-annotation.lua").read_text(), "-- user's file\n")
            self.assertFalse((config / "init.lua").exists())

    def test_consumer_loader_with_missing_default_checkout_is_not_reported_as_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".config/rex"
            config.mkdir(parents=True)
            init = config / "init.lua"
            init.write_text('require("annotate")\n')
            (config / "annotate.lua").write_text(
                '-- rex-annotation consumer\nlocal root = os.getenv("REX_ANNOTATION_HOME") or '
                '(os.getenv("HOME") .. "/work/personal/rex-annotation")\nreturn dofile(root .. "/rex/annotate.lua")\n')
            result = self.run_install(home, "--rex")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("consumer", result.stderr.lower())
            self.assertFalse((config / "rex-annotation.lua").exists())
            self.assertEqual(init.read_text(), 'require("annotate")\n')

    def test_codex_install_merges_hooks_idempotently_without_removing_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            codex = home / ".codex"
            codex.mkdir()
            unrelated = {"matcher":"startup", "hooks":[{"type":"command", "command":"echo unrelated"}]}
            (codex / "hooks.json").write_text(json.dumps({"description":"keep me", "hooks":{"SessionStart":[unrelated]}}))
            for _ in range(2):
                result = self.run_install(home, "--codex")
                self.assertEqual(result.returncode, 0, result.stderr)
            installed = json.loads((codex / "hooks.json").read_text())
            self.assertEqual(installed["description"], "keep me")
            self.assertEqual(installed["hooks"]["SessionStart"][0], unrelated)
            self.assertEqual(len(installed["hooks"]["SessionStart"]), 2)
            self.assertEqual(len(installed["hooks"]["UserPromptSubmit"]), 1)
            self.assertTrue((home / ".agents/skills/rex-annotation").is_symlink())
            self.assertIn("trust", result.stdout.lower())

    def test_migrate_owned_legacy_loader_without_duplicate_require(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            config=home/'.config/rex'
            config.mkdir(parents=True)
            (config/'rex_annotation.lua').write_text('-- Installed by rex-annotation; only the repository path lives here.\nreturn dofile([[/old/rex/annotate.lua]])\n')
            (config/'init.lua').write_text('require("unrelated")\nrequire("rex_annotation") -- old\n')
            result=self.run_install(home)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual((config/'init.lua').read_text().count('require("rex-annotation")'),1)
            self.assertNotIn('require("rex_annotation")',(config/'init.lua').read_text())
            self.assertIn('require("unrelated")',(config/'init.lua').read_text())
            self.assertTrue((config/'rex_annotation.lua').exists())

    def test_unknown_referenced_legacy_loader_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            config=home/'.config/rex'
            config.mkdir(parents=True)
            (config/'rex_annotation.lua').write_text('-- unrelated feature\n')
            original='require("unrelated")\nrequire("rex_annotation")\n'
            (config/'init.lua').write_text(original)
            result=self.run_install(home)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((config/'init.lua').read_text(),original)
            self.assertFalse((config/'rex-annotation.lua').exists())

    def test_codex_upgrade_replaces_only_owned_handlers_not_unrelated_mentions(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)
            config=home/'.codex'
            config.mkdir()
            unrelated={"type":"command","command":"echo /old/integrations/codex/hooks/register.py"}
            old={"type":"command","command":"python3 /old/integrations/codex/hooks/register.py"}
            (config/'hooks.json').write_text(json.dumps({"hooks":{"SessionStart":[{"hooks":[unrelated,old]}]}}))
            result=self.run_install(home,'--codex')
            self.assertEqual(result.returncode,0,result.stderr)
            contents=json.loads((config/'hooks.json').read_text())['hooks']
            self.assertIn(unrelated,contents['SessionStart'][0]['hooks'])
            self.assertNotIn(old,contents['SessionStart'][0]['hooks'])
            self.assertIn(str(ROOT/'integrations/codex/hooks/register.py'),json.dumps(contents))

    def test_pi_setup_calls_only_package_registration_and_surfaces_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            commands=base/'commands'
            commands.mkdir()
            executable=commands/'pi'
            log=base/'pi.json'
            executable.write_text('#!'+sys.executable+'\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["PI_TEST_LOG"]).write_text(json.dumps(sys.argv[1:]))\nsys.exit(int(os.environ.get("PI_TEST_EXIT","0")))\n')
            executable.chmod(0o755)
            old={key:os.environ.get(key) for key in ('PATH','PI_TEST_LOG','PI_TEST_EXIT')}
            try:
                os.environ.update({'PATH':str(commands)+os.pathsep+os.environ['PATH'],'PI_TEST_LOG':str(log)})
                first=base/'first'
                first.mkdir()
                result=self.run_install(first,'--pi')
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(log.read_text()),['install',str(ROOT)])
                os.environ['PI_TEST_EXIT']='7'
                second=base/'second'
                second.mkdir()
                result=self.run_install(second,'--pi')
                self.assertNotEqual(result.returncode,0)
                self.assertIn('exit code 7',result.stderr)
                self.assertFalse((second/'.config/rex/rex-annotation.lua').exists())
            finally:
                for key,value in old.items():
                    if value is None: os.environ.pop(key,None)
                    else: os.environ[key]=value

    def test_long_lua_path_quotes_cannot_break_out(self):
        value = '/tmp/odd path]]and]=]"plugin/rex/annotate.lua'
        quoted = INSTALL.lua_string(value)
        self.assertEqual(quoted, "[==[" + value + "]==]")


if __name__ == "__main__":
    unittest.main()
