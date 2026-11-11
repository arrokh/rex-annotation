import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class FirstRunTests(unittest.TestCase):
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
                         "PI_CODING_AGENT_DIR":str(home/".pi/agent"),"PATH":str(commands),"TEST_CALLS":str(calls),
                         "PYTHONDONTWRITEBYTECODE":"1"}
            result=subprocess.run([sys.executable,str(ROOT/"bin/rex-annotation"),"install","--detect","--reload-rex"],
                                  env=environment,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Detected agents: claude, codex, pi',result.stdout)
            self.assertTrue((home/".local/bin/rex-annotation").is_symlink())
            self.assertIn('require("rex-annotation")',(home/".config/rex/init.lua").read_text())
            installed=json.loads((home/".pi/agent/settings.json").read_text())
            self.assertEqual(installed["packages"],[str(ROOT)])
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


if __name__=="__main__":
    unittest.main()
