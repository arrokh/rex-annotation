import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "integrations"))
import session_replies as replies


class CuxBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR": str(Path(self.temp.name) / "state")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.transcript = str(ROOT / "integrations/tests/fixtures/claude_session.jsonl")
        self.args = ("claude", os.getpid(), "session", "block", "claude-synthetic-1", self.transcript)
        self.children = []

    def child(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.children.append(process)
        return process

    def tearDown(self):
        for process in self.children:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)

    def test_child_exit_invalidates_binding(self):
        child = self.child()
        replies.register_binding(*self.args, native_child_pid=child.pid)
        child.terminate()
        child.wait(timeout=3)
        with self.assertRaisesRegex(replies.ReplyError, "native child"):
            replies._current_binding(os.getpid(), "claude", "session", "block")

    def test_old_end_cannot_remove_new_same_conversation_child(self):
        old, new = self.child(), self.child()
        replies.register_binding(*self.args, native_child_pid=old.pid)
        replies.register_binding(*self.args, native_child_pid=new.pid)
        self.assertFalse(replies.unregister_binding(*self.args[:5], native_child_pid=old.pid))
        replies._current_binding(os.getpid(), "claude", "session", "block")
        self.assertTrue(replies.unregister_binding(*self.args[:5], native_child_pid=new.pid))

    def test_resume_can_register_after_the_previous_child_exited(self):
        old = self.child()
        replies.register_binding(*self.args, native_child_pid=old.pid)
        old.terminate()
        old.wait(timeout=3)
        self.assertFalse(replies.invalidate_binding(*self.args[:4]))
        new = self.child()
        replies.register_binding(*self.args, native_child_pid=new.pid)
        _, record = replies._current_binding(os.getpid(), "claude", "session", "block")
        self.assertEqual(record["native_child_pid"], new.pid)
        self.assertFalse(replies.unregister_binding(*self.args[:5], native_child_pid=old.pid))

    def test_malformed_or_reused_child_identity_is_rejected(self):
        child = self.child()
        record = replies.register_binding(*self.args, native_child_pid=child.pid)
        path = replies._binding_path(replies._state_directory(), os.getpid(), record['process_start'])
        import json
        for changes in ({'native_child_pid': True}, {'native_child_start': ''}, {'native_child_start': 'changed-start'}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**record, **changes}))
                with self.assertRaisesRegex(replies.ReplyError, 'native child'):
                    replies._current_binding(os.getpid(), 'claude', 'session', 'block')

    def test_ordinary_binding_and_bad_child_pid(self):
        record = replies.register_binding(*self.args)
        self.assertNotIn("native_child_pid", record)
        self.assertTrue(replies._current_binding(os.getpid(), "claude", "session", "block"))
        with self.assertRaises(replies.ReplyError):
            replies.register_binding(*self.args, native_child_pid=0)


if __name__ == "__main__":
    unittest.main()
