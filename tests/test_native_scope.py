import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "integrations"))
import native_scope
from session_replies import ReplyError


class NativeScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rex-native-scope-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.rex = self.directory / "rex"
        self.log = self.directory / "args.json"
        self.env = {"REX_SESSION": "exact-session", "REX_BLOCK": "exact-block"}
        self.output = {"last_exit": None, "foreground": {"pid": 42, "path": "/opt/codex"}}
        self.write_rex()
        self.environment = mock.patch.dict(os.environ, {"PATH": str(self.directory) + os.pathsep + os.environ["PATH"]})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write_rex(self, body=None):
        if body is None:
            body = "import json,sys\nfrom pathlib import Path\nPath({!r}).write_text(json.dumps(sys.argv[1:]))\nprint({!r})\n".format(
                str(self.log), json.dumps(self.output))
        self.rex.write_text("#!" + sys.executable + "\n" + body)
        self.rex.chmod(0o755)

    def graph(self, parents=None, paths=None):
        parents = parents or {100: 50, 50: 42, 42: 1}
        paths = paths or {42: "/opt/codex"}
        def info(pid):
            if pid not in parents:
                raise ReplyError("missing owned test process")
            return native_scope.ProcessInfo(pid, parents[pid], os.geteuid(), "test:" + str(pid), paths.get(pid, "/usr/bin/python3"))
        return info

    def resolve(self, *, env=None, parents=None, paths=None, agent="codex"):
        with mock.patch.object(native_scope, "_process_info", side_effect=self.graph(parents, paths)):
            return native_scope.rex_scope(agent, self.env if env is None else env, 100)

    def test_plain_command_queries_exact_pane_and_verifies_native_ancestor(self):
        self.assertEqual(self.resolve(), ("exact-session", "exact-block", 42))
        self.assertEqual(json.loads(self.log.read_text()), ["--autostart=false", "--timeout", "1s", "block", "call",
                                                           "-s", "exact-session", "-b", "exact-block", "process"])

    def test_outside_or_partial_rex_context_is_noop_without_query(self):
        for env in ({}, {"REX_SESSION": "only-session"}, {"REX_BLOCK": "only-block"}):
            with self.subTest(env=env), mock.patch.object(native_scope, "_run_rex_process") as query:
                self.assertIsNone(self.resolve(env=env))
                query.assert_not_called()

    def test_global_hooks_outside_rex_do_not_even_parse_input(self):
        environment = {key:value for key,value in os.environ.items()
                       if key not in ("REX_SESSION", "REX_BLOCK", "REX_PID", "REX_ANNOTATION_ROOT")}
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                result = subprocess.run([sys.executable, str(ROOT / "integrations" / agent / "hooks/register.py")],
                                        env=environment, input="not JSON and must not be read", text=True,
                                        capture_output=True, timeout=5)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertFalse(self.log.exists())

    def test_background_and_nested_native_clis_cannot_bind_foreground(self):
        self.assertIsNone(self.resolve(parents={100: 50, 50: 1, 42: 1}))
        self.assertIsNone(self.resolve(paths={42: "/opt/codex", 50: "/nested/codex"}))
        self.assertIsNone(self.resolve(env={**self.env, "REX_PID": "42"}, paths={42: "/opt/codex", 50: "/nested/codex"}))

    def test_explicit_launcher_scope_is_supported_without_a_rex_query(self):
        with mock.patch.object(native_scope, "_run_rex_process") as query:
            self.assertEqual(self.resolve(env={**self.env, "REX_PID": "42"}), ("exact-session", "exact-block", 42))
            query.assert_not_called()

    def test_wrong_agent_invalid_pid_and_reused_process_are_rejected(self):
        self.assertIsNone(self.resolve(agent="claude"))
        for pid in (False, 0, -1, "42"):
            with self.subTest(pid=pid):
                self.output["foreground"]["pid"] = pid
                self.write_rex()
                self.assertIsNone(self.resolve())
        with self.assertRaises(ReplyError):
            self.resolve(env={**self.env, "REX_PID": "-1"})
        with mock.patch.object(native_scope, "_process_info", side_effect=self.graph()):
            self.assertFalse(native_scope._is_ancestor(42, "different-start", 100, "codex"))

    def test_versioned_claude_native_executable_is_recognized(self):
        self.output["foreground"]["path"] = "/Users/test/.local/share/claude/versions/2.1.322"
        self.write_rex()
        self.assertEqual(self.resolve(agent="claude", paths={42: self.output["foreground"]["path"]}),
                         ("exact-session", "exact-block", 42))

    def test_cux_is_claude_with_separate_native_child_identity(self):
        self.output['foreground']['path'] = '/opt/cux'
        self.write_rex()
        graph = {100: 60, 60: 50, 50: 42, 42: 1}
        paths = {42: '/opt/cux', 50: '/opt/claude'}
        with mock.patch.object(native_scope, '_process_info', side_effect=self.graph(graph, paths)):
            scope = native_scope.resolve_scope('claude', self.env, 100)
        self.assertEqual(scope[:3], ('exact-session', 'exact-block', 42))
        self.assertEqual(scope.native_child_pid, 50)
        paths[60] = '/nested/claude'
        with mock.patch.object(native_scope, '_process_info', side_effect=self.graph(graph, paths)):
            self.assertIsNone(native_scope.resolve_scope('claude', self.env, 100))

    def test_query_rejects_malformed_oversized_and_stalled_output(self):
        for body, message in (("print('not-json')", "malformed"),
                              ("print('x' * 65537)", "oversized"),
                              ("import time;time.sleep(5)", "timed out")):
            with self.subTest(message=message):
                self.write_rex(body)
                with self.assertRaisesRegex(ReplyError, message):
                    native_scope._run_rex_process("exact-session", "exact-block")

    def test_cycles_and_deep_ancestry_are_bounded(self):
        with mock.patch.object(native_scope, "_process_info", side_effect=self.graph({100: 50, 50: 100, 42: 1})):
            self.assertFalse(native_scope._is_ancestor(42, "test:42", 100, "codex"))
        parents = {pid: pid - 1 for pid in range(100, 1000)}
        parents[42] = 1
        with mock.patch.object(native_scope, "_process_info", side_effect=self.graph(parents)) as info:
            self.assertFalse(native_scope._is_ancestor(42, "test:42", 999, "codex"))
            self.assertLessEqual(info.call_count, native_scope.MAX_ANCESTRY_DEPTH)

    def test_real_owned_child_can_verify_its_parent_without_ps(self):
        parent = os.getpid()
        code = ("import os,sys;sys.path.insert(0,sys.argv[1]);import native_scope;"
                "pid=int(sys.argv[2]);info=native_scope._process_info(pid);"
                "assert native_scope._is_ancestor(pid,info.start_identity,os.getpid(),'codex')")
        result = subprocess.run([sys.executable, "-c", code, str(ROOT / "integrations"), str(parent)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
