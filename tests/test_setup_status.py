import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("annotation_setup_status", ROOT / "scripts/status.py")
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class SetupStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.environment = mock.patch.dict(os.environ, {"HOME":str(self.home), "XDG_CONFIG_HOME":str(self.home/".config"),
                               "PI_CODING_AGENT_DIR":str(self.home/".pi/agent"), "CODEX_HOME":str(self.home/".codex")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        config = self.home/".config/rex"
        config.mkdir(parents=True)
        (config/"rex-annotation.lua").write_text('return dofile([['+str(ROOT/"rex/annotate.lua")+']])\n')
        (config/"init.lua").write_text('require("rex-annotation")\n')

    def probe(self, command, timeout=5):
        if "actions" in command:
            return 0, json.dumps({"actions":[{"name":"annotate_open"}]})
        return 0, "valid"

    def report(self, requested=(), missing=()):
        with mock.patch.object(STATUS.shutil,"which",side_effect=lambda name:None if name in missing else '/fake/'+name), \
             mock.patch.object(STATUS,"_run",side_effect=self.probe):
            return STATUS.collect_status(requested)

    def test_required_missing_neovim_cannot_report_success(self):
        report,failed=self.report(missing={"nvim"})
        self.assertTrue(failed)
        self.assertEqual(report["overall"],"fail")
        self.assertEqual(next(c for c in report["checks"] if c["name"]=="neovim_features")["status"],"fail")

    def test_relative_pi_paths_resolve_from_settings_not_current_working_directory(self):
        settings=self.home/".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"packages":[os.path.relpath(ROOT,settings.parent)]}))
        self.assertEqual(STATUS._pi_installed(self.home)[0],"installed")

    def test_disabled_pi_extension_is_not_reported_installed(self):
        settings=self.home/".pi/agent/settings.json"
        settings.parent.mkdir(parents=True)
        for patterns in ([],["!integrations/pi/**"],["other/*.js"]):
            with self.subTest(patterns=patterns):
                settings.write_text(json.dumps({"packages":[{"source":str(ROOT),"extensions":patterns}]}))
                report,failed=self.report(requested={"pi"})
                self.assertTrue(failed)
                self.assertEqual(next(c for c in report["checks"] if c["name"]=="pi_registration")["status"],"fail")

    def test_setup_checks_are_read_only_and_do_not_claim_runtime_trust(self):
        before={str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        calls=[]
        def probe(command,timeout=5):
            calls.append(command)
            return self.probe(command,timeout)
        with mock.patch.object(STATUS.shutil,"which",side_effect=lambda n:'/fake/'+n),mock.patch.object(STATUS,"_run",side_effect=probe):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                code=STATUS.main(["--json"])
        self.assertEqual(code,0)
        report=json.loads(output.getvalue())
        self.assertEqual(report["overall"],"attention")
        self.assertTrue(all(set(c)=={"name","status","detail","fix"} for c in report["checks"]))
        self.assertEqual(before,{str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        self.assertFalse(any('install' in c or 'reload' in c for c in calls))
        self.assertTrue(any('actions' in c and '--autostart=false' in c for c in calls))

    def test_timeout_output_bytes_produce_actionable_result_not_traceback(self):
        with mock.patch.object(STATUS.subprocess,"run",side_effect=subprocess.TimeoutExpired(['fixture'],1,output=b'partial',stderr=b'error')):
            code,detail=STATUS._run(['fixture'],timeout=1)
        self.assertIsNone(code)
        self.assertIn('partialerror',detail)

    def test_stale_dynamic_consumer_path_is_not_accepted_by_marker_alone(self):
        loader=self.home/'.config/rex/rex-annotation.lua'
        loader.write_text('-- rex-annotation\nlocal root=os.getenv("REX_ANNOTATION_HOME") or (os.getenv("HOME") .. "/work/personal/rex-annotation")\nreturn dofile(root .. "/rex/annotate.lua")\n')
        self.assertFalse(STATUS._loader_matches_root(loader))

    def test_one_codex_hook_is_not_a_complete_install(self):
        skill=self.home/'.agents/skills/rex-annotation'
        skill.parent.mkdir(parents=True)
        skill.symlink_to(ROOT/'integrations/codex/skills/rex-annotation')
        hooks=self.home/'.codex/hooks.json'
        hooks.parent.mkdir()
        hooks.write_text(json.dumps({"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"python3 "+str(ROOT/'integrations/codex/hooks/register.py')}]}]}}))
        self.assertEqual(STATUS._codex_state(self.home)[0],'partial')


if __name__=='__main__':
    unittest.main()
