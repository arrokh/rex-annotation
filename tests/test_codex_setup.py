import importlib.util
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("codex_setup", ROOT / "scripts/codex_setup.py")
CODEX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CODEX)


FAKE_CODEX = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json
    import os
    import sys
    import time

    state_path = os.environ["CODEX_SETUP_FIXTURE_STATE"]
    log_path = os.environ["CODEX_SETUP_FIXTURE_LOG"]
    pid_path = os.environ["CODEX_SETUP_FIXTURE_PID"]
    with open(pid_path, "w") as stream:
        stream.write(str(os.getpid()))

    def load_state():
        with open(state_path) as stream:
            return json.load(stream)

    def save_state(state):
        with open(state_path, "w") as stream:
            json.dump(state, stream)

    def record(request):
        with open(log_path, "a") as stream:
            stream.write(json.dumps(request) + "\\n")

    def respond(request, result=None, error=None):
        response = {"id": request["id"]}
        if error is not None:
            response["error"] = error
        else:
            response["result"] = result
        sys.stdout.write(json.dumps(response) + "\\n")
        sys.stdout.flush()

    for raw in sys.stdin:
        request = json.loads(raw)
        record(request)
        if request.get("method") == "initialized":
            continue
        method = request.get("method")
        scenario = os.environ.get("CODEX_SETUP_FIXTURE_MODE", "")
        target = os.environ.get("CODEX_SETUP_FIXTURE_TARGET", "hooks/list")
        if scenario in ("rpc-error", "stall", "eof", "oversize") and method == target:
            if scenario == "rpc-error":
                respond(request, error={"code": -32601, "message": "method not found"})
            elif scenario == "stall":
                time.sleep(3)
            elif scenario == "eof":
                sys.exit(0)
            else:
                sys.stdout.write("x" * 4096 + "\\n")
                sys.stdout.flush()
            continue
        if method == "initialize":
            version = os.environ.get("CODEX_SETUP_FIXTURE_VERSION", "0.167.1")
            respond(request, {"userAgent": "codex-cli/" + version + " (fixture)", "codexHome": os.environ["CODEX_HOME"]})
            continue
        state = load_state()
        if method == "config/read":
            config = state["config"]
            features = dict(config.get("features", {}))
            result = {
                "config": {"features": features},
                "origins": {},
                "layers": [
                    {
                        "name": {"type": "user", "file": state["config_file"], "profile": None},
                        "version": state["version"],
                        "config": config,
                    }
                ],
            }
            respond(request, result)
        elif method == "configRequirements/read":
            respond(request, {"requirements": state.get("requirements")})
        elif method == "hooks/list":
            hooks = []
            for hook in state["hooks"]:
                item = dict(hook)
                if state["trust"].get(item["key"]) == item["currentHash"]:
                    item["trustStatus"] = "trusted"
                respond_hook = item
                hooks.append(respond_hook)
            respond(request, {"data": [{"cwd": state["cwd"], "hooks": hooks, "warnings": [], "errors": []}]})
        elif method == "config/batchWrite":
            params = request["params"]
            if params.get("expectedVersion") != state["version"]:
                respond(request, error={"code": -32010, "message": "config version conflict"})
                continue
            for edit in params["edits"]:
                if edit["keyPath"] == "features.hooks":
                    state["config"].setdefault("features", {})["hooks"] = edit["value"]
                elif edit["keyPath"] == "hooks.state":
                    state["trust"].update({key: value["trusted_hash"] for key, value in edit["value"].items()})
                    state["config"].setdefault("hooks", {}).setdefault("state", {}).update(edit["value"])
                else:
                    respond(request, error={"code": -32602, "message": "unexpected config edit"})
                    continue
            state["version"] = "sha256:updated-" + str(state.get("write_count", 0) + 1)
            state["write_count"] = state.get("write_count", 0) + 1
            save_state(state)
            respond(request, {"status": "ok", "version": state["version"], "filePath": state["config_file"], "overriddenMetadata": None})
        else:
            respond(request, error={"code": -32601, "message": "method not found: " + str(method)})
''')


class CodexSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.codex_home = self.home / ".codex"
        self.codex_home.mkdir()
        self.root = ROOT.resolve()
        self.hook_file = self.codex_home / "hooks.json"
        self.fake = self.base / "codex"
        self.fake.write_text(FAKE_CODEX)
        self.fake.chmod(0o755)
        self.state_path = self.base / "state.json"
        self.log_path = self.base / "rpc.jsonl"
        self.pid_path = self.base / "pid"
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(self.home),
            "CODEX_HOME": str(self.codex_home),
            "CODEX_SETUP_FIXTURE_STATE": str(self.state_path),
            "CODEX_SETUP_FIXTURE_LOG": str(self.log_path),
            "CODEX_SETUP_FIXTURE_PID": str(self.pid_path),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.which = mock.patch.object(CODEX.shutil, "which", return_value=str(self.fake))
        self.which.start()
        self.addCleanup(self.which.stop)

    def make_hooks(self):
        template = json.loads((self.root / "integrations/codex/hooks/hooks.json").read_text())
        command = "python3 " + CODEX.shlex.quote(str(self.root / "integrations/codex/hooks/register.py"))
        hooks = []
        for event, groups in template["hooks"].items():
            for group_index, group in enumerate(groups):
                for handler_index, handler in enumerate(group["hooks"]):
                    event_name = event[0].lower() + event[1:]
                    hooks.append({
                        "key": "{}:{}:{}:{}".format(self.hook_file, event.lower(), group_index, handler_index),
                        "eventName": event_name,
                        "handlerType": "command",
                        "command": command,
                        "async": False,
                        "matcher": group.get("matcher"),
                        "timeoutSec": handler.get("timeout"),
                        "statusMessage": handler.get("statusMessage"),
                        "additionalContextLimit": None,
                        "sourcePath": str(self.hook_file),
                        "source": "user",
                        "pluginId": None,
                        "environmentId": None,
                        "displayOrder": len(hooks),
                        "enabled": True,
                        "isManaged": False,
                        "currentHash": "sha256:{}".format(str(len(hooks) + 1) * 64)[:71],
                        "trustStatus": "untrusted",
                    })
        return hooks

    def state(self, *, feature=None, hooks=None, requirements=None, config=None):
        layer_config = config or {"model": "unrelated-model", "features": {"other_feature": True},
                                 "hooks": {"state": {"unrelated-hook": {"enabled": False}}}}
        data = {
            "cwd": str(self.home.resolve()),
            "config_file": str(self.codex_home / "config.toml"),
            "version": "sha256:original-user-config",
            "config": layer_config,
            "hooks": hooks if hooks is not None else self.make_hooks(),
            "requirements": requirements,
            "trust": {},
            "write_count": 0,
        }
        if feature is not None:
            data["config"].setdefault("features", {})["hooks"] = feature
        self.state_path.write_text(json.dumps(data))
        self.log_path.write_text("")
        self.pid_path.unlink(missing_ok=True)
        return data

    def requests(self):
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line]

    def read_state(self):
        return json.loads(self.state_path.read_text())

    def run_configure(self):
        with mock.patch.object(CODEX.shutil, "which", return_value=str(self.fake)):
            return CODEX.configure_codex(self.root, self.home)

    def run_inspect(self):
        with mock.patch.object(CODEX.shutil, "which", return_value=str(self.fake)):
            return CODEX.inspect_codex(self.root, self.home)

    def test_configure_trusts_only_exact_owned_hooks_and_preserves_unrelated_config(self):
        original = self.state()
        result = self.run_configure()
        self.assertEqual(result["status"], "ok")
        self.assertIn("detail", result)
        requests = self.requests()
        writes = [request for request in requests if request.get("method") == "config/batchWrite"]
        self.assertEqual(len(writes), 1)
        params = writes[0]["params"]
        self.assertEqual(params["expectedVersion"], original["version"])
        self.assertTrue(params["reloadUserConfig"])
        edits = {edit["keyPath"]: edit for edit in params["edits"]}
        self.assertEqual(edits["features.hooks"]["value"], True)
        self.assertEqual(edits["hooks.state"]["mergeStrategy"], "upsert")
        self.assertEqual(set(edits["hooks.state"]["value"]), {hook["key"] for hook in original["hooks"]})
        saved = self.read_state()
        self.assertEqual(saved["config"]["model"], "unrelated-model")
        self.assertEqual(saved["config"]["features"]["other_feature"], True)
        self.assertEqual(saved["config"]["hooks"]["state"]["unrelated-hook"], {"enabled": False})
        self.assertTrue(all(saved["trust"][hook["key"]] == hook["currentHash"] for hook in original["hooks"]))
        self.assertFalse(any(request.get("method") in ("thread/start", "turn/start") for request in requests))

    def test_unrelated_hooks_with_the_same_event_and_matcher_remain_unapproved(self):
        hooks = self.make_hooks()
        unrelated = dict(hooks[-1], key="unrelated-stop-hook", command="echo keep unrelated")
        hooks.append(unrelated)
        self.state(hooks=hooks)
        self.assertEqual(self.run_configure()["status"], "ok")
        saved = self.read_state()
        self.assertNotIn(unrelated["key"], saved["trust"])
        self.assertIn(unrelated, saved["hooks"])

    def test_stable_symlink_install_root_retains_the_exact_installed_command(self):
        alias = self.base / "stable opt root"
        alias.symlink_to(ROOT, target_is_directory=True)
        self.root = alias
        self.state()
        self.assertEqual(self.run_configure()["status"], "ok")
        self.assertEqual(self.run_inspect()["status"], "ok")

    def test_configure_is_idempotent_after_native_trust_and_feature_activation(self):
        self.state()
        self.run_configure()
        first_writes = [r for r in self.requests() if r.get("method") == "config/batchWrite"]
        self.run_configure()
        all_writes = [r for r in self.requests() if r.get("method") == "config/batchWrite"]
        self.assertEqual(len(first_writes), 1)
        self.assertEqual(len(all_writes), 1)

    def test_inspect_is_read_only_and_reports_pending_trust(self):
        self.state()
        result = self.run_inspect()
        self.assertEqual(result["status"], "needs-setup")
        self.assertTrue(any("trust" in item.lower() or "feature" in item.lower()
                            for item in result.values() if isinstance(item, str)))
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))

    def test_sibling_source_hook_is_never_approved(self):
        hooks = self.make_hooks()
        hooks[0]["sourcePath"] = str(self.base / "other" / "hooks.json")
        hooks[0]["key"] = str(self.base / "other" / "hooks.json") + ":session_start:0:0"
        self.state(hooks=hooks)
        with self.assertRaises(CODEX.CodexSetupError):
            self.run_configure()
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))

    def test_modified_command_in_owned_source_fails_closed(self):
        hooks = self.make_hooks()
        hooks[0]["command"] += "; echo malicious"
        self.state(hooks=hooks)
        with self.assertRaises(CODEX.CodexSetupError):
            self.run_configure()
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))

    def test_explicitly_disabled_hook_is_not_reenabled(self):
        hooks = self.make_hooks()
        hooks[0]["enabled"] = False
        self.state(hooks=hooks)
        with self.assertRaises(CODEX.CodexSetupError):
            self.run_configure()
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))

    def test_managed_hooks_only_policy_is_preserved_and_reported(self):
        self.state(requirements={"hooks": {"allowManagedHooksOnly": True}})
        result = self.run_inspect()
        self.assertEqual(result["status"], "blocked")
        with self.assertRaises(CODEX.CodexSetupError):
            self.run_configure()
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))

    def test_explicit_feature_disable_is_preserved_and_reported(self):
        self.state(feature=False)
        result = self.run_inspect()
        self.assertEqual(result["status"], "blocked")
        with self.assertRaises(CODEX.CodexSetupError):
            self.run_configure()
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))

    def test_rpc_error_includes_upgrade_guidance(self):
        self.state()
        with mock.patch.dict(os.environ, {"CODEX_SETUP_FIXTURE_MODE": "rpc-error", "CODEX_SETUP_FIXTURE_TARGET": "hooks/list"}):
            with self.assertRaises(CODEX.CodexSetupError) as caught:
                self.run_configure()
        self.assertIn("Codex", str(caught.exception))
        self.assertIn("upgrade", str(caught.exception).lower())

    def test_stall_eof_and_oversized_output_fail_and_reap_owned_process(self):
        for mode in ("stall", "eof", "oversize"):
            with self.subTest(mode=mode):
                self.state()
                self.pid_path.unlink(missing_ok=True)
                with mock.patch.object(CODEX, "_RPC_TIMEOUT_SECONDS", 0.15), \
                     mock.patch.object(CODEX, "_MAX_RPC_OUTPUT_BYTES", 1024), \
                     mock.patch.dict(os.environ, {"CODEX_SETUP_FIXTURE_MODE": mode, "CODEX_SETUP_FIXTURE_TARGET": "hooks/list"}):
                    with self.assertRaises(CODEX.CodexSetupError):
                        self.run_configure()
                pid = int(self.pid_path.read_text())
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_older_codex_protocol_is_rejected_before_configuration_access(self):
        self.state()
        with mock.patch.dict(os.environ, {"CODEX_SETUP_FIXTURE_VERSION": "0.167.0"}):
            with self.assertRaises(CODEX.CodexSetupError) as caught:
                self.run_configure()
        self.assertIn("upgrade", str(caught.exception).lower())
        self.assertFalse(any(r.get("method") == "config/batchWrite" for r in self.requests()))


if __name__ == "__main__":
    unittest.main()
