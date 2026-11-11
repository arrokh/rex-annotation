import importlib.util
import json
import os
from pathlib import Path
import shlex
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
                                   "CODEX_HOME": str(home / ".codex"), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                                   "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=5)

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

    def test_claude_install_merges_hooks_idempotently_and_preserves_unrelated_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".claude"
            config.mkdir()
            unrelated = {"matcher": "Startup", "hooks": [{"type": "command", "command": "echo keep"}]}
            settings = config / "settings.json"
            untouched_group = {"matcher": "*"}
            settings.write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["Read"]},
                                            "hooks": {"SessionStart": [unrelated], "PreToolUse": [untouched_group]}}))
            settings.chmod(0o640)
            snapshots = []
            for _ in range(2):
                result = self.run_install(home, "--claude")
                self.assertEqual(result.returncode, 0, result.stderr)
                snapshots.append(settings.read_bytes())
            self.assertEqual(snapshots[0], snapshots[1])
            installed = json.loads(settings.read_text())
            self.assertEqual(installed["theme"], "dark")
            self.assertEqual(installed["permissions"], {"allow": ["Read"]})
            self.assertEqual(installed["hooks"]["SessionStart"][0], unrelated)
            self.assertEqual(installed["hooks"]["PreToolUse"][0], untouched_group)
            template = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
            for event in template:
                handlers = [handler for group in installed["hooks"][event] for handler in group.get("hooks", [])
                            if handler.get("type") == "command" and "integrations/claude/hooks/register.py" in handler.get("command", "")]
                self.assertEqual(len(handlers), 1, event)
                self.assertEqual(handlers[0]["command"], "python3 " + shlex.quote(str(ROOT / "integrations/claude/hooks/register.py")))
            self.assertIn("normal codex/claude", result.stdout)
            self.assertEqual(settings.stat().st_mode & 0o777, 0o640)

    def test_claude_install_migrates_stale_owned_paths_without_touching_unrelated_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude/settings.json"
            settings.parent.mkdir()
            stale = {"type": "command", "command": "python3 /old/integrations/claude/hooks/register.py"}
            unrelated = {"type": "command", "command": "python3 /old/not-claude/register.py"}
            settings.write_text(json.dumps({"hooks": {"SessionEnd": [{"hooks": [stale, unrelated]}]}}))
            result = self.run_install(home, "--claude")
            self.assertEqual(result.returncode, 0, result.stderr)
            handlers = json.loads(settings.read_text())["hooks"]["SessionEnd"][0]["hooks"]
            self.assertIn(unrelated, handlers)
            self.assertNotIn(stale, handlers)
            self.assertIn(str(ROOT / "integrations/claude/hooks/register.py"), settings.read_text())
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", settings.read_text())

    def test_claude_custom_config_dir_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            config = Path(directory) / "custom-claude-config"
            home.mkdir()
            config.mkdir()
            result = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"), "--claude"],
                                   env={**os.environ, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config),
                                        "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((config / "settings.json").is_file())
            self.assertFalse((home / ".claude/settings.json").exists())

    def test_malformed_claude_settings_fail_before_any_install_plan_is_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".claude"
            config.mkdir()
            settings = config / "settings.json"
            malformed = [
                ("{broken", "Invalid Claude settings file"),
                (json.dumps([]), "Invalid Claude settings object"),
                (json.dumps({"hooks": []}), "Invalid hooks object"),
                (json.dumps({"hooks": {"SessionStart": [None]}}), "Invalid hook group"),
                (json.dumps({"hooks": {"SessionStart": [{"hooks": [None]}]}}), "Invalid hook handler"),
            ]
            init = home / ".config/rex/init.lua"
            for original, error_text in malformed:
                with self.subTest(settings=original):
                    settings.write_text(original)
                    result = self.run_install(home, "--claude")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error_text, result.stderr)
                    self.assertEqual(settings.read_text(), original)
                    self.assertFalse(init.exists())
                    self.assertFalse((home / ".local/bin/rex-annotation").exists())

    def test_claude_install_preserves_disable_all_hooks_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude/settings.json"
            settings.parent.mkdir()
            settings.write_text(json.dumps({"disableAllHooks": True, "other": "preserved"}))
            result = self.run_install(home, "--claude")
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = json.loads(settings.read_text())
            self.assertTrue(installed["disableAllHooks"])
            self.assertEqual(installed["other"], "preserved")

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
