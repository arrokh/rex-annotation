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
                               "PI_CODING_AGENT_DIR":str(self.home/".pi/agent"), "CODEX_HOME":str(self.home/".codex"),
                               "CLAUDE_CONFIG_DIR":str(self.home/".claude")})
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

    def write_claude_hooks(self, path=None):
        path = path or self.home/".claude/settings.json"
        template = json.loads((ROOT/"hooks/hooks.json").read_text())["hooks"]
        hooks = {}
        command = "python3 " + str(ROOT/"integrations/claude/hooks/register.py")
        for event, groups in template.items():
            hooks[event] = json.loads(json.dumps(groups))
            for group in hooks[event]:
                for handler in group["hooks"]:
                    handler["command"] = command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hooks": hooks}))
        return path

    def test_claude_status_requires_complete_automatic_hooks(self):
        absent, _ = self.report(requested={"claude"})
        self.assertEqual(next(c for c in absent["checks"] if c["name"] == "claude_hooks")["status"], "fail")

        settings = self.home/".claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
            {"type": "command", "command": "python3 " + str(ROOT/"integrations/claude/hooks/register.py")}
        ]}]}}))
        partial, _ = self.report()
        self.assertEqual(next(c for c in partial["checks"] if c["name"] == "claude_hooks")["status"], "fail")

        complete_path = self.write_claude_hooks()
        self.assertEqual(STATUS._claude_hooks_state(self.home)[0], "installed")
        complete, failed = self.report(requested={"claude"})
        self.assertFalse(failed)
        self.assertEqual(next(c for c in complete["checks"] if c["name"] == "claude_hooks")["status"], "ok")
        self.assertEqual(next(c for c in complete["checks"] if c["name"] == "claude_runtime")["status"], "unknown")
        self.assertIn("normal claude", next(c for c in complete["checks"] if c["name"] == "claude_runtime")["fix"])

    def test_claude_status_does_not_accept_a_nonmatching_sessionstart_filter(self):
        path = self.write_claude_hooks()
        settings = json.loads(path.read_text())
        settings["hooks"]["SessionStart"][0]["matcher"] = "not-a-real-start-source"
        path.write_text(json.dumps(settings))
        self.assertEqual(STATUS._claude_hooks_state(self.home)[0], "partial")

    def test_claude_status_honors_custom_config_dir_and_disable_all_hooks(self):
        custom = self.home/"custom-claude"
        self.write_claude_hooks(custom/"settings.json")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(custom)}):
            self.assertEqual(STATUS._claude_hooks_state(self.home)[0], "installed")

        (custom/"settings.json").write_text(json.dumps({"disableAllHooks": True, "hooks": {}}))
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(custom)}):
            state, detail, _ = STATUS._claude_hooks_state(self.home)
            self.assertEqual(state, "blocked")
            self.assertIn("disableAllHooks is true", detail)
            report, failed = self.report(requested={"claude"})
            check = next(c for c in report["checks"] if c["name"] == "claude_hooks")
            self.assertEqual(check["status"], "blocked")
            self.assertIn("preserves this policy", check["fix"])
            self.assertTrue(failed)

    def test_cux_counts_as_claude_not_a_separate_agent(self):
        report, _ = self.report(requested={"claude"}, missing={"claude"})
        check = next(c for c in report["checks"] if c["name"] == "claude_cli")
        self.assertEqual(check["status"], "ok")
        self.assertIn("CUX", check["detail"])
        self.assertFalse(any(c["name"].startswith("cux_") for c in report["checks"]))
        report, _ = self.report(requested={"claude"}, missing={"claude", "cux"})
        check = next(c for c in report["checks"] if c["name"] == "claude_cli")
        self.assertEqual(check["status"], "fail")

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
        self.assertEqual(report["overall"],"ok")
        self.assertEqual(next(c for c in report["checks"] if c["name"]=="claude_hooks")["status"],"not-installed")
        self.assertFalse(any(c["name"]=="claude_runtime" for c in report["checks"]))
        self.assertIn("does not indicate user activation",next(c for c in report["checks"] if c["name"]=="claude_plugin")["detail"])
        self.assertTrue(all(set(c)=={"name","status","detail","fix"} for c in report["checks"]))
        self.assertEqual(before,{str(p.relative_to(self.home)):p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        self.assertFalse(any('install' in c or 'reload' in c for c in calls))
        self.assertTrue(any('actions' in c and '--autostart=false' in c for c in calls))

    def test_codex_status_verifies_native_trust_and_reports_pending_setup_as_failure(self):
        skill = self.home/".agents/skills/rex-annotation"
        skill.parent.mkdir(parents=True)
        skill.symlink_to(ROOT/"integrations/codex/skills/rex-annotation")
        template = json.loads((ROOT/"integrations/codex/hooks/hooks.json").read_text())
        for groups in template["hooks"].values():
            for group in groups:
                for handler in group["hooks"]:
                    handler["command"] = "python3 " + str(ROOT/"integrations/codex/hooks/register.py")
        hooks = self.home/".codex/hooks.json"
        hooks.parent.mkdir()
        hooks.write_text(json.dumps(template))
        import codex_setup
        for native, expected, failed_expected in (("ok", "ok", False), ("needs-setup", "fail", True),
                                                  ("blocked", "blocked", True)):
            with self.subTest(native=native), mock.patch.object(codex_setup, "inspect_codex",
                    return_value={"status": native, "detail": "native fixture"}):
                report, failed = self.report(requested={"codex"})
                self.assertEqual(failed, failed_expected)
                check = next(item for item in report["checks"] if item["name"] == "codex_trust")
                self.assertEqual(check["status"], expected)
                self.assertNotIn("/hooks", check["fix"])

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
