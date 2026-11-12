import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

INTEGRATIONS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INTEGRATIONS))
import session_replies as replies  # noqa: E402
import native_scope  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
CODEX_ID = "11111111-1111-4111-8111-111111111111"
CLAUDE_ID = "claude-synthetic-1"


class SessionRepliesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_home = Path(self.temporary.name) / "state"
        self.old_state = os.environ.get("REX_ANNOTATION_STATE_DIR")
        os.environ["REX_ANNOTATION_STATE_DIR"] = str(self.state_home)

    def tearDown(self):
        if self.old_state is None:
            os.environ.pop("REX_ANNOTATION_STATE_DIR", None)
        else:
            os.environ["REX_ANNOTATION_STATE_DIR"] = self.old_state

    def transcript_copy(self, fixture, filename=None):
        destination = Path(self.temporary.name) / (filename or fixture)
        shutil.copyfile(FIXTURES / fixture, destination)
        return str(destination)

    def register(self, agent="codex", path=None, conversation=None, pid=None, session="rex-session", block="b1"):
        if path is None:
            fixture = "codex_session.jsonl" if agent == "codex" else "claude_session.jsonl"
            path = self.transcript_copy(fixture)
        if conversation is None:
            conversation = CODEX_ID if agent == "codex" else CLAUDE_ID
        return replies.register_binding(agent, pid or os.getpid(), session, block, conversation, path)

    def run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = replies.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_codex_extracts_only_visible_assistant_items_oldest_first(self):
        path = self.transcript_copy("codex_session.jsonl")
        result = replies._parse_transcript("codex", path, CODEX_ID)
        self.assertEqual([item["text"] for item in result], ["First answer.", "Second answer.", "Working..."])
        self.assertEqual(result[0]["id"], "codex-reply-1")
        self.assertEqual(result[1]["timestamp"], "2026-01-02T03:04:10.000Z")
        self.assertNotIn("hidden reasoning", json.dumps(result))
        self.assertNotIn("hidden channel reasoning", json.dumps(result))
        self.assertNotIn("secret user prompt", json.dumps(result))
        self.assertNotIn("hidden tool", json.dumps(result))

    def test_claude_extracts_text_blocks_and_strips_terminal_escapes(self):
        path = self.transcript_copy("claude_session.jsonl")
        result = replies._parse_transcript("claude", path, CLAUDE_ID)
        self.assertEqual([item["text"] for item in result], ["First answer.", "Second answer."])
        self.assertEqual(result[0]["id"], "assistant-1")
        self.assertNotIn("hidden reasoning", json.dumps(result))
        self.assertNotIn("hidden sidechain", json.dumps(result))
        self.assertNotIn("hidden compaction summary", json.dumps(result))
        self.assertNotIn("\\u001b", json.dumps(result))

    def test_cli_shape_and_binding_permissions(self):
        home = Path(self.temporary.name) / "codex-home"
        directory = home / "sessions/2026/01/02"
        directory.mkdir(parents=True)
        path = directory / ("rollout-2026-01-02T03-04-05-" + CODEX_ID + ".jsonl")
        path.write_text((FIXTURES / "codex_session.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        path = str(path)
        record = self.register(path=path)
        directory = Path(record["transcript_path"])
        binding_dir = self.state_home / "rex-annotation" / "reply-bindings"
        binding_file = replies._binding_path(binding_dir, os.getpid(), record["process_start"])
        self.assertEqual(binding_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(binding_file.stat().st_mode & 0o777, 0o600)
        metadata = binding_file.read_text(encoding="utf-8")
        self.assertNotIn("First answer", metadata)
        self.assertEqual(directory, Path(path).resolve())

        process = {"foreground":{"pid":os.getpid(),"path":"/opt/homebrew/bin/codex"}}
        process_info = native_scope.ProcessInfo(os.getpid(), 1, os.geteuid(),
                                                replies._process_start_identity(os.getpid()), "/opt/homebrew/bin/codex")
        with mock.patch.object(native_scope, "_run_rex_process", return_value=process), \
             mock.patch.object(native_scope, "_process_info", return_value=process_info), \
             mock.patch.object(native_scope, "_open_codex_rollouts", return_value=[str(Path(path).resolve())]):
            status, stdout, stderr = self.run_cli([
                "replies", "--agent", "codex", "--pid", str(os.getpid()),
                "--session", "rex-session", "--block", "b1",
            ])
            self.assertEqual((status, stderr), (0, ""))
            result = json.loads(stdout)
            self.assertEqual(result["sessionId"], CODEX_ID)
            self.assertEqual(result["replies"][0]["text"], "First answer.")

            status, stdout, stderr = self.run_cli([
                "validate", "--agent", "codex", "--pid", str(os.getpid()),
                "--session", "rex-session", "--block", "b1", "--conversation", CODEX_ID,
            ])
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(json.loads(stdout), {"valid": True, "sessionId": CODEX_ID})

    def test_binding_mismatch_and_changed_native_session_fail(self):
        path = self.transcript_copy("codex_session.jsonl")
        self.register(path=path)
        with self.assertRaisesRegex(replies.ReplyError, "rex_block"):
            replies._verified_binding("codex", os.getpid(), "rex-session", "other")
        with self.assertRaisesRegex(replies.ReplyError, "conversation id changed"):
            replies._verified_binding("codex", os.getpid(), "rex-session", "b1", "other-id")

        Path(path).write_text(
            (FIXTURES / "codex_session.jsonl").read_text(encoding="utf-8").replace(CODEX_ID, "22222222-2222-4222-8222-222222222222"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(replies.ReplyError, "does not match"):
            replies._verified_binding("codex", os.getpid(), "rex-session", "b1", CODEX_ID)

    def test_unregistration_from_old_session_cannot_remove_new_binding(self):
        first = self.transcript_copy("codex_session.jsonl", "first.jsonl")
        second = self.transcript_copy("codex_session.jsonl", "second.jsonl")
        replies.register_binding("codex", os.getpid(), "rex-session", "b1", CODEX_ID, first)
        new_id = "33333333-3333-4333-8333-333333333333"
        Path(second).write_text(
            Path(second).read_text(encoding="utf-8").replace(CODEX_ID, new_id), encoding="utf-8"
        )
        replies.register_binding("codex", os.getpid(), "rex-session", "b1", new_id, second)
        self.assertFalse(replies.unregister_binding("codex", os.getpid(), "rex-session", "b1", CODEX_ID))
        current = replies._verified_binding("codex", os.getpid(), "rex-session", "b1", new_id)
        self.assertEqual(current["transcript_path"], str(Path(second).resolve()))
        with self.assertRaisesRegex(replies.ReplyError, "conversation id changed"):
            replies._verified_binding("codex", os.getpid(), "rex-session", "b1", CODEX_ID)

    def test_stale_process_binding_is_rejected(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
        try:
            path = self.transcript_copy("claude_session.jsonl", "claude-synthetic-1.jsonl")
            self.register("claude", path, CLAUDE_ID, child.pid)
        finally:
            child.wait(timeout=5)
        with self.assertRaisesRegex(replies.ReplyError, "no longer running"):
            replies._verified_binding("claude", child.pid, "rex-session", "b1", CLAUDE_ID)

    def test_reused_pid_start_identity_does_not_reuse_binding(self):
        path = self.transcript_copy("codex_session.jsonl")
        with mock.patch.object(replies, "_process_start_identity", return_value="test-start-1"):
            replies.register_binding("codex", 987654, "rex-session", "b1", CODEX_ID, path)
        with mock.patch.object(replies, "_process_start_identity", return_value="test-start-2"):
            with self.assertRaisesRegex(replies.ReplyError, "no active reply binding"):
                replies._verified_binding("codex", 987654, "rex-session", "b1", CODEX_ID)

    def test_claude_mismatched_session_and_ambiguous_branch_fail(self):
        path = self.transcript_copy("claude_session.jsonl", "other-session.jsonl")
        data = Path(path).read_text(encoding="utf-8").replace(CLAUDE_ID, "different-session")
        Path(path).write_text(data, encoding="utf-8")
        with self.assertRaisesRegex(replies.ReplyError, "does not match"):
            replies._parse_transcript("claude", path, CLAUDE_ID)

        branch = Path(self.temporary.name) / "branch.jsonl"
        common = {"type": "user", "uuid": "root", "parentUuid": None, "sessionId": CLAUDE_ID, "timestamp": "2026-01-02T03:04:05Z", "message": {"role": "user", "content": []}}
        assistant = {"type": "assistant", "sessionId": CLAUDE_ID, "timestamp": "2026-01-02T03:04:06Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "branch"}]}}
        left = dict(assistant, uuid="left", parentUuid="root")
        right = dict(assistant, uuid="right", parentUuid="root")
        branch.write_text("\n".join(json.dumps(item) for item in (common, left, right)) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(replies.ReplyError, "ambiguous active branch"):
            replies._parse_transcript("claude", str(branch), CLAUDE_ID)

    def test_malformed_control_oversize_and_entry_limit_fail_closed(self):
        path = Path(self.temporary.name) / "bad.jsonl"
        path.write_text('{"type":"session_meta"}\nnot json\n', encoding="utf-8")
        with self.assertRaisesRegex(replies.ReplyError, "malformed transcript entry"):
            replies._parse_transcript("codex", str(path), CODEX_ID)

        control = (FIXTURES / "claude_session.jsonl").read_text(encoding="utf-8").replace(
            "Second answer.", "bad\\u0001text"
        )
        path.write_text(control, encoding="utf-8")
        with self.assertRaisesRegex(replies.ReplyError, "control characters"):
            replies._parse_transcript("claude", str(path), CLAUDE_ID)

        path.write_bytes(b"x" * (replies.MAX_TRANSCRIPT_BYTES + 1))
        with self.assertRaisesRegex(replies.ReplyError, "4 MiB"):
            replies._parse_transcript("claude", str(path), CLAUDE_ID)

        path.write_text("\n".join('{"type":"event"}' for _ in range(5001)) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(replies.ReplyError, "5000-entry"):
            replies._parse_transcript("claude", str(path), CLAUDE_ID)

    def test_codex_native_hooks_register_refresh_and_remove_exact_session(self):
        path = self.transcript_copy("codex_session.jsonl")
        payload = {
            "hook_event_name": "SessionStart", "session_id": CODEX_ID,
            "transcript_path": path, "cwd": "/synthetic/project", "source": "startup",
        }
        script = INTEGRATIONS / "codex" / "hooks" / "register.py"
        environment = dict(os.environ, REX_SESSION="rex-session", REX_BLOCK="hook-block", REX_PID=str(os.getpid()))
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        bound = replies._verified_binding("codex", os.getpid(), "rex-session", "hook-block", CODEX_ID)
        self.assertEqual(bound["transcript_path"], str(Path(path).resolve()))

        payload["hook_event_name"] = "SessionEnd"
        payload["reason"] = "other"
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(replies.ReplyError, "no active reply binding"):
            replies._verified_binding("codex", os.getpid(), "rex-session", "hook-block", CODEX_ID)

    def test_claude_plugin_hooks_register_stop_refresh_and_remove_session(self):
        path = self.transcript_copy("claude_session.jsonl", "claude-synthetic-1.jsonl")
        payload = {
            "hook_event_name": "SessionStart", "source": "startup", "session_id": CLAUDE_ID,
            "transcript_path": path, "cwd": "/synthetic/project",
        }
        script = INTEGRATIONS / "claude" / "hooks" / "register.py"
        environment = dict(os.environ, REX_SESSION="rex-session", REX_BLOCK="claude-block", REX_PID=str(os.getpid()))
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            replies._verified_binding("claude", os.getpid(), "rex-session", "claude-block", CLAUDE_ID)["transcript_path"],
            str(Path(path).resolve()),
        )

        payload["hook_event_name"] = "Stop"
        payload["last_assistant_message"] = "not persisted by the hook"
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload["hook_event_name"] = "SessionEnd"
        payload["reason"] = "other"
        result = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(replies.ReplyError, "no active reply binding"):
            replies._verified_binding("claude", os.getpid(), "rex-session", "claude-block", CLAUDE_ID)

    def test_codex_skill_script_registers_exact_thread_id(self):
        home = Path(self.temporary.name) / "codex-home"
        sessions = home / "sessions" / "2026" / "01" / "02"
        sessions.mkdir(parents=True)
        transcript = sessions / "rollout-2026-01-02T03-04-05-{}.jsonl".format(CODEX_ID)
        transcript.write_text((FIXTURES / "codex_session.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        environment = dict(
            os.environ,
            CODEX_HOME=str(home),
            CODEX_THREAD_ID=CODEX_ID,
            REX_SESSION="rex-session",
            REX_BLOCK="skill-block",
            REX_PID=str(os.getpid()),
        )
        script = INTEGRATIONS / "codex" / "skills" / "rex-annotation" / "scripts" / "register_current.py"
        result = subprocess.run([sys.executable, str(script)], text=True, capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(CODEX_ID, result.stdout)
        binding = replies._verified_binding("codex", os.getpid(), "rex-session", "skill-block", CODEX_ID)
        self.assertEqual(binding["transcript_path"], str(transcript.resolve()))

    def test_codex_skill_transcript_lookup_uses_exact_thread_and_rejects_ambiguity(self):
        home = Path(self.temporary.name) / "codex-home"
        sessions = home / "sessions" / "2026" / "01" / "02"
        sessions.mkdir(parents=True)
        exact = sessions / "rollout-2026-01-02T03-04-05-{}.jsonl".format(CODEX_ID)
        exact.write_text((FIXTURES / "codex_session.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        other_id = "22222222-2222-4222-8222-222222222222"
        unrelated = sessions / "rollout-2026-01-02T23-59-59-{}.jsonl".format(other_id)
        unrelated.write_text("not a transcript we read\n", encoding="utf-8")
        self.assertEqual(replies.find_codex_transcript(CODEX_ID, str(home)), str(exact.resolve()))

        second = sessions / "rollout-2026-01-02T03-04-06-{}_{}.jsonl".format(CODEX_ID, str(uuid.uuid4()))
        second.write_text((FIXTURES / "codex_session.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(replies.ReplyError, "multiple Codex rollouts"):
            replies.find_codex_transcript(CODEX_ID, str(home))

    def test_cli_stale_binding_returns_actionable_error(self):
        path = self.transcript_copy("claude_session.jsonl")
        self.register("claude", path, CLAUDE_ID)
        status, stdout, stderr = self.run_cli([
            "validate", "--agent", "claude", "--pid", str(os.getpid()),
            "--session", "wrong-rex-session", "--block", "b1", "--conversation", CLAUDE_ID,
        ])
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("does not match rex_session", stderr)


if __name__ == "__main__":
    unittest.main()
