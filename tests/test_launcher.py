import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class LauncherTests(unittest.TestCase):
    def test_exec_preserves_bound_pid_and_adds_only_claude_plugin_option(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for agent in ("codex", "claude"):
                executable = base / agent
                executable.write_text('#!' + sys.executable + '\nimport json,os,sys\n'
                                      'print(json.dumps({"pid":os.getpid(),"args":sys.argv[1:],'
                                      '"bound":os.environ["REX_PID"],"root":os.environ["REX_ANNOTATION_ROOT"]}))\n')
                executable.chmod(0o755)
                result = subprocess.run([sys.executable, str(ROOT / "bin/rex-annotation"), agent, "synthetic prompt"],
                                        env={**os.environ, "PATH":str(base) + os.pathsep + os.environ["PATH"],
                                             "REX_SESSION":"owned-session", "REX_BLOCK":"owned-block"},
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                reported = json.loads(result.stdout)
                self.assertEqual(str(reported["pid"]), reported["bound"])
                self.assertEqual(reported["root"], str(ROOT))
                expected = ["synthetic prompt"] + (["--plugin-dir", str(ROOT)] if agent == "claude" else [])
                self.assertEqual(reported["args"], expected)

    def test_explicit_brew_style_opt_root_is_preserved_not_resolved_to_cellar(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            alias=base/'opt-libexec'
            alias.symlink_to(ROOT,target_is_directory=True)
            executable=base/'codex'
            executable.write_text('#!'+sys.executable+'\nimport os;print(os.environ["REX_ANNOTATION_ROOT"])\n')
            executable.chmod(0o755)
            environment={**os.environ,'PATH':str(base)+os.pathsep+os.environ['PATH'],'REX_SESSION':'owned','REX_BLOCK':'owned',
                         'REX_ANNOTATION_ROOT':str(alias)}
            result=subprocess.run([sys.executable,str(ROOT/'bin/rex-annotation'),'codex'],env=environment,capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),str(alias))
            result=subprocess.run([sys.executable,str(ROOT/'bin/rex-annotation'),'install'],
                                  env={**environment,'HOME':str(base/'home'),'XDG_CONFIG_HOME':str(base/'config')},
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(str(alias/'rex/annotate.lua'),(base/'config/rex/rex-annotation.lua').read_text())

    def test_outside_rex_fails_without_launching_an_agent(self):
        environment = {key:value for key,value in os.environ.items() if key not in ("REX_SESSION", "REX_BLOCK")}
        result = subprocess.run([sys.executable, str(ROOT / "bin/rex-annotation"), "codex"],
                                env=environment, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Rex pane", result.stderr)


if __name__ == "__main__":
    unittest.main()
