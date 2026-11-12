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
import native_scope


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

    def test_codex_recovers_missing_startup_binding_from_one_open_foreground_rollout(self):
        conversation = "11111111-1111-4111-8111-111111111111"
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            transcript = Path(directory) / "sessions/2026/01/02" / (
                "rollout-2026-01-02T03-04-05-" + conversation + ".jsonl"
            )
            transcript.parent.mkdir(parents=True)
            transcript.write_text((ROOT / "integrations/tests/fixtures/codex_session.jsonl").read_text())
            process = {"foreground":{"pid":os.getpid(),"path":"/opt/homebrew/bin/codex"}}
            process_info = native_scope.ProcessInfo(os.getpid(), 1, os.geteuid(),
                                                    replies._process_start_identity(os.getpid()), "/opt/homebrew/bin/codex")
            with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}), \
                 mock.patch.object(native_scope, "_run_rex_process", return_value=process), \
                 mock.patch.object(native_scope, "_process_info", return_value=process_info), \
                 mock.patch.object(native_scope, "_open_codex_rollouts", return_value=[str(transcript.resolve())]):
                _, binding = replies._recover_codex_binding(os.getpid(), "owned-session", "owned-block")
                self.assertEqual(binding["conversation_id"], conversation)
                self.assertEqual(Path(binding["transcript_path"]), transcript.resolve())
                self.assertEqual(replies._verified_binding("codex", os.getpid(), "owned-session", "owned-block"), binding)

    def test_codex_rejects_existing_binding_when_foreground_rollout_changes(self):
        old_id = "11111111-1111-4111-8111-111111111111"
        new_id = "22222222-2222-4222-8222-222222222222"
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            sessions = Path(directory) / "sessions/2026/01/02"
            sessions.mkdir(parents=True)
            old_path = sessions / ("rollout-2026-01-02T03-04-05-" + old_id + ".jsonl")
            new_path = sessions / ("rollout-2026-01-02T03-04-06-" + new_id + ".jsonl")
            fixture = (ROOT / "integrations/tests/fixtures/codex_session.jsonl").read_text()
            old_path.write_text(fixture)
            new_path.write_text(fixture.replace(old_id, new_id))
            process = {"foreground":{"pid":os.getpid(),"path":"/opt/homebrew/bin/codex"}}
            process_info = native_scope.ProcessInfo(os.getpid(), 1, os.geteuid(),
                                                    replies._process_start_identity(os.getpid()), "/opt/homebrew/bin/codex")
            with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}):
                replies.register_binding("codex", os.getpid(), "owned-session", "owned-block", old_id, str(old_path))
                with mock.patch.object(native_scope, "_run_rex_process", return_value=process), \
                     mock.patch.object(native_scope, "_process_info", return_value=process_info), \
                     mock.patch.object(native_scope, "_open_codex_rollouts", return_value=[str(new_path.resolve())]):
                    with self.assertRaisesRegex(replies.ReplyError, "changed without a matching lifecycle binding"):
                        replies._current_or_recover_binding(os.getpid(), "codex", "owned-session", "owned-block")
                binding_path, binding = replies._current_binding(os.getpid(), "codex", "owned-session", "owned-block")
                self.assertEqual(binding["conversation_id"], old_id)
                self.assertEqual(Path(binding["transcript_path"]), old_path.resolve())
                self.assertEqual(binding_path, replies._binding_path(state / "rex-annotation/reply-bindings", os.getpid(), binding["process_start"]))

    def test_codex_recovery_refuses_ambiguous_or_nonforeground_rollouts(self):
        conversation = "11111111-1111-4111-8111-111111111111"
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            transcripts = []
            for suffix in ("", "_22222222-2222-4222-8222-222222222222"):
                path = Path(directory) / ("sessions/2026/01/02/rollout-2026-01-02T03-04-05-" + conversation + suffix + ".jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text((ROOT / "integrations/tests/fixtures/codex_session.jsonl").read_text())
                transcripts.append(str(path))
            process = {"foreground":{"pid":os.getpid(),"path":"/opt/homebrew/bin/codex"}}
            process_info = native_scope.ProcessInfo(os.getpid(), 1, os.geteuid(),
                                                    replies._process_start_identity(os.getpid()), "/opt/homebrew/bin/codex")
            with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}), \
                 mock.patch.object(native_scope, "_run_rex_process", return_value=process), \
                 mock.patch.object(native_scope, "_process_info", return_value=process_info), \
                 mock.patch.object(native_scope, "_open_codex_rollouts", return_value=[str(Path(path).resolve()) for path in transcripts]):
                with self.assertRaisesRegex(replies.ReplyError, "multiple Codex rollouts"):
                    replies._recover_codex_binding(os.getpid(), "owned-session", "owned-block")
                self.assertFalse(list((state / "rex-annotation/reply-bindings").glob("*.json")))
            with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}), \
                 mock.patch.object(native_scope, "_run_rex_process", return_value=process), \
                 mock.patch.object(native_scope, "_process_info", return_value=process_info), \
                 mock.patch.object(native_scope, "_open_codex_rollouts", return_value=[]):
                with self.assertRaisesRegex(replies.ReplyError, "no Codex rollout is open"):
                    replies._recover_codex_binding(os.getpid(), "owned-session", "owned-block")
                self.assertFalse(list((state / "rex-annotation/reply-bindings").glob("*.json")))
            process["foreground"]["pid"] = os.getpid() + 1
            with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}), \
                 mock.patch.object(native_scope, "_run_rex_process", return_value=process), \
                 mock.patch.object(native_scope, "_open_codex_rollouts") as open_files:
                with self.assertRaisesRegex(replies.ReplyError, "foreground Codex process changed"):
                    replies._recover_codex_binding(os.getpid(), "owned-session", "owned-block")
                open_files.assert_not_called()

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

    def test_native_sessionstart_can_bind_before_transcript_exists_without_creating_it(self):
        for agent, conversation in (("codex", "11111111-1111-4111-8111-111111111111"), ("claude", "claude-synthetic-1")):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                state=Path(directory)/"state"
                source=Path(directory)/"not-created"/(conversation+".jsonl")
                environment={**os.environ,"REX_ANNOTATION_STATE_DIR":str(state),"REX_SESSION":"owned-session","REX_BLOCK":"owned-block",
                             "REX_PID":str(os.getpid()),"PYTHONDONTWRITEBYTECODE":"1"}
                event={"hook_event_name":"SessionStart","source":"startup","session_id":conversation,"transcript_path":str(source)}
                result=subprocess.run([sys.executable,str(ROOT/"integrations"/agent/"hooks/register.py")],env=environment,
                                      input=json.dumps(event),capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertFalse(source.exists())
                arguments=["--agent",agent,"--pid",str(os.getpid()),"--session","owned-session","--block","owned-block"]
                listed=subprocess.run([sys.executable,str(ROOT/"integrations/session_replies.py"),"replies",*arguments],
                                      env=environment,capture_output=True,text=True,timeout=5)
                self.assertEqual(listed.returncode,0,listed.stderr)
                self.assertEqual(json.loads(listed.stdout)["replies"],[])
                validated=subprocess.run([sys.executable,str(ROOT/"integrations/session_replies.py"),"validate",*arguments,"--conversation",conversation],
                                         env=environment,capture_output=True,text=True,timeout=5)
                self.assertNotEqual(validated.returncode,0)  # Delivery still needs an actual matching transcript.
                source.parent.mkdir()
                source.write_text((ROOT/"integrations/tests/fixtures"/(agent+"_session.jsonl")).read_text())
                if agent == "codex":
                    with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR":str(state)}):
                        record = replies._verified_binding(agent, os.getpid(), "owned-session", "owned-block", conversation)
                    self.assertEqual(record["conversation_id"], conversation)
                else:
                    validated=subprocess.run([sys.executable,str(ROOT/"integrations/session_replies.py"),"validate",*arguments,"--conversation",conversation],
                                             env=environment,capture_output=True,text=True,timeout=5)
                    self.assertEqual(validated.returncode,0,validated.stderr)

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
