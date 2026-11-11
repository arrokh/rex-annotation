import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class FirstRunTests(unittest.TestCase):
    def test_detect_cux_only_installs_claude_hooks_without_launching_cux(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            commands = home / 'commands'
            commands.mkdir()
            (commands / 'python3').symlink_to(sys.executable)
            cux = commands / 'cux'
            cux.write_text('#!' + sys.executable + '\nraise RuntimeError("CUX must not be launched by setup/status")\n')
            cux.chmod(0o755)
            env = {**os.environ, 'HOME': str(home), 'PATH': str(commands),
                   'XDG_CONFIG_HOME': str(home / '.config'), 'CLAUDE_CONFIG_DIR': str(home / '.claude'),
                   'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, str(ROOT / 'bin/rex-annotation'), 'install', '--detect'],
                                    env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Detected agents: claude', result.stdout)
            self.assertTrue((home / '.claude/settings.json').is_file())
            self.assertFalse((home / '.codex/hooks.json').exists())

    def test_fresh_home_detect_setup_reload_and_status_without_agent_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home, commands = base/"home", base/"commands"
            home.mkdir()
            commands.mkdir()
            calls = base/"calls.jsonl"
            common = '#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\n'
            (commands/"python3").symlink_to(sys.executable)
            (commands/"nvim").write_text(common + 'sys.exit(0)\n')
            (commands/"rex").write_text(common +
                'with open(os.environ["TEST_CALLS"],"a") as f:f.write(json.dumps(["rex",*sys.argv[1:]])+"\\n")\n'
                'print(json.dumps({"actions":[{"name":"annotate_open"}]}) if "actions" in sys.argv else "ok")\n')
            (commands/"pi").write_text(common +
                'assert sys.argv[1]=="install"\n'
                'with open(os.environ["TEST_CALLS"],"a") as f:f.write(json.dumps(["pi",*sys.argv[1:]])+"\\n")\n'
                'p=Path(os.environ["PI_CODING_AGENT_DIR"])/"settings.json";p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({"packages":[sys.argv[2]]}))\n')
            for agent in ("codex","claude"):
                (commands/agent).write_text(common + 'raise RuntimeError("An agent must not be launched by setup/status")\n')
            for executable in commands.iterdir():
                if not executable.is_symlink():executable.chmod(0o755)
            environment={**os.environ,"HOME":str(home),"XDG_CONFIG_HOME":str(home/".config"),"CODEX_HOME":str(home/".codex"),
                         "CLAUDE_CONFIG_DIR":str(home/".claude"),"PI_CODING_AGENT_DIR":str(home/".pi/agent"),
                         "PATH":str(commands),"TEST_CALLS":str(calls),
                         "PYTHONDONTWRITEBYTECODE":"1"}
            result=subprocess.run([sys.executable,str(ROOT/"bin/rex-annotation"),"install","--detect","--reload-rex"],
                                  env=environment,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Detected agents: claude, codex, pi',result.stdout)
            self.assertTrue((home/".local/bin/rex-annotation").is_symlink())
            self.assertIn('require("rex-annotation")',(home/".config/rex/init.lua").read_text())
            installed=json.loads((home/".pi/agent/settings.json").read_text())
            self.assertEqual(installed["packages"],[str(ROOT)])
            claude_settings=json.loads((home/".claude/settings.json").read_text())
            expected_claude_events=set(json.loads((ROOT/"hooks/hooks.json").read_text())["hooks"])
            self.assertEqual(set(claude_settings["hooks"]),expected_claude_events)
            claude_handlers=[handler for groups in claude_settings["hooks"].values() for group in groups
                             for handler in group.get("hooks", [])]
            self.assertTrue(claude_handlers)
            self.assertTrue(all(handler["command"] == "python3 " + str(ROOT/"integrations/claude/hooks/register.py")
                                for handler in claude_handlers))
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", json.dumps(claude_settings))
            recorded=[json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(recorded,[["pi","install",str(ROOT)],["rex","config","check"],["rex","config","reload"]])
            environment["PATH"]=str(home/".local/bin")+os.pathsep+str(commands)
            status=subprocess.run([sys.executable,str(ROOT/"bin/rex-annotation"),"status","--json"],
                                  env=environment,capture_output=True,text=True,timeout=10)
            self.assertEqual(status.returncode,0,status.stderr)
            report=json.loads(status.stdout)
            self.assertEqual(report["overall"],"attention")
            self.assertFalse([check for check in report["checks"] if check["status"]=="fail"])
            self.assertEqual(next(c["status"] for c in report["checks"] if c["name"]=="codex_trust"),"manual")
            self.assertEqual(next(c["status"] for c in report["checks"] if c["name"]=="claude_hooks"),"ok")
            self.assertEqual(next(c["status"] for c in report["checks"] if c["name"]=="claude_runtime"),"unknown")


if __name__=="__main__":
    unittest.main()
