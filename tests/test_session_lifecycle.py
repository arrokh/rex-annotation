import importlib.util
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
import session_replies as replies


class LifecycleTests(unittest.TestCase):
    def test_failed_new_session_registration_invalidates_old_conversation(self):
        for agent, conversation in (("codex", "11111111-1111-4111-8111-111111111111"), ("claude", "claude-synthetic-1")):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                state = Path(directory) / "state"
                with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}):
                    transcript = ROOT / "integrations/tests/fixtures" / (agent + "_session.jsonl")
                    replies.register_binding(agent, os.getpid(), "owned-session", "owned-block", conversation, str(transcript))
                    payload = {"hook_event_name":"SessionStart", "session_id":"new-session-without-persistence", "source":"clear"}
                    result = subprocess.run([sys.executable, str(ROOT / "integrations" / agent / "hooks/register.py")],
                                            input=json.dumps(payload), text=True, capture_output=True, timeout=5,
                                            env={**os.environ, "REX_SESSION":"owned-session", "REX_BLOCK":"owned-block", "REX_PID":str(os.getpid())})
                    self.assertNotEqual(result.returncode, 0)
                    with self.assertRaisesRegex(replies.ReplyError, "no active reply binding"):
                        replies._current_binding(os.getpid(), agent, "owned-session", "owned-block")

    def test_codex_native_message_phases_include_final_and_partial_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            conversation = "11111111-1111-4111-8111-111111111111"
            rows = [{"type":"session_meta", "payload":{"id":conversation}}]
            for index, phase in enumerate(("commentary", "partial_answer", "final_answer")):
                rows.append({"type":"response_item", "timestamp":"2026-01-02T03:04:0%dZ" % index,
                             "payload":{"type":"message", "role":"assistant", "phase":phase,
                                        "content":[{"type":"output_text", "text":phase}]}})
            transcript = Path(directory) / "native.jsonl"
            transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
            self.assertEqual([item["text"] for item in replies._parse_transcript("codex", str(transcript), conversation)],
                             ["commentary", "partial_answer", "final_answer"])

    def test_codex_rollback_cannot_silently_reexport_undone_replies(self):
        with tempfile.TemporaryDirectory() as directory:
            conversation = "11111111-1111-4111-8111-111111111111"
            rows = [json.loads(line) for line in (ROOT / "integrations/tests/fixtures/codex_session.jsonl").read_text().splitlines()]
            rows.append({"type":"event_msg", "timestamp":"2026-01-02T03:04:12Z", "payload":{"type":"thread_rolled_back", "num_turns":1}})
            transcript = Path(directory) / "rollback.jsonl"
            transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
            with self.assertRaisesRegex(replies.ReplyError, "rollback"):
                replies._parse_transcript("codex", str(transcript), conversation)

    def test_blank_assistant_blocks_are_not_selectable_replies(self):
        for agent, conversation in (("codex", "11111111-1111-4111-8111-111111111111"), ("claude", "claude-synthetic-1")):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                rows = [json.loads(line) for line in (ROOT / "integrations/tests/fixtures" / (agent + "_session.jsonl")).read_text().splitlines()]
                if agent == "codex":
                    rows.append({"type":"response_item", "timestamp":"2026-01-02T03:04:12Z", "payload":{"type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"   "}]}})
                else:
                    rows.append({"type":"assistant", "uuid":"blank", "parentUuid":"assistant-2", "sessionId":conversation, "timestamp":"2026-01-02T03:04:12Z", "message":{"role":"assistant", "content":[{"type":"text", "text":"   "}]}})
                transcript = Path(directory) / "fixture.jsonl"
                transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
                actual = replies._parse_transcript(agent, str(transcript), conversation)
                self.assertTrue(actual)
                self.assertTrue(all(row["text"].strip() for row in actual))


if __name__ == "__main__":
    unittest.main()
