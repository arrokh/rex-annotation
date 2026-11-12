"""Claude's streamed response blocks and parallel tool results are not rewinds."""
import copy
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

SESSION = "claude-parallel-fixture"


def entry(kind, uuid, parent, content=None, response=None, **extra):
    row = {"type": kind, "uuid": uuid, "parentUuid": parent, "sessionId": SESSION,
           "timestamp": "2026-01-02T03:04:05Z", **extra}
    if content is not None:
        row["message"] = {"role": kind, "content": content}
        if response is not None:
            row["message"]["id"] = response
    return row


def parallel_rows():
    # Match the real failing shape: a response streams tools while their results
    # arrive. Each result points at its own call, not the last streamed block.
    return [
        entry("user", "prompt", None, "PRIVATE USER"),
        entry("assistant", "intro", "prompt", [{"type": "text", "text": "Before tools."}], "response-1", apiBlockIndex=0),
        entry("assistant", "call-a", "intro", [{"type": "tool_use", "id": "tool-a", "name": "Read", "input": {}}], "response-1", apiBlockIndex=1),
        entry("assistant", "call-b", "call-a", [{"type": "tool_use", "id": "tool-b", "name": "Read", "input": {}}], "response-1", apiBlockIndex=2),
        entry("user", "result-a", "call-a", [{"type": "tool_result", "tool_use_id": "tool-a", "content": "PRIVATE RESULT A"}]),
        entry("user", "result-b", "call-b", [{"type": "tool_result", "tool_use_id": "tool-b", "content": "PRIVATE RESULT B"}]),
        entry("assistant", "call-c", "result-a", [{"type": "tool_use", "id": "tool-c", "name": "Read", "input": {}}], "response-1", apiBlockIndex=3),
        entry("user", "result-c", "call-c", [{"type": "tool_result", "tool_use_id": "tool-c", "content": "PRIVATE RESULT C"}]),
        entry("attachment", "context", "result-c", attachment={"type": "fixture", "content": "PRIVATE CONTEXT"}),
        entry("assistant", "answer", "context", [{"type": "thinking", "thinking": "PRIVATE REASONING"},
                                                   {"type": "text", "text": "After tools. | é猫"}], "response-2"),
    ]


class ClaudeParallelToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / (SESSION + ".jsonl")

    def parse(self, rows):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return replies._parse_transcript("claude", str(self.path), SESSION)

    def test_interleaved_parallel_tool_results_keep_all_visible_text(self):
        result = self.parse(parallel_rows())
        self.assertEqual([r["text"] for r in result], ["Before tools.", "After tools. | é猫"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual([r["id"] for r in result], ["intro", "answer"])

    def test_each_partial_prefix_is_readable_while_tools_are_running(self):
        rows = parallel_rows()
        for end in range(2, len(rows) + 1):
            with self.subTest(end=end):
                result = self.parse(rows[:end])
                self.assertEqual(result[0]["text"], "Before tools.")

    def test_progress_links_are_opaque_and_preserve_visible_replies(self):
        rows = parallel_rows()
        rows.insert(1, entry("progress", "progress-node", "prompt", data={"text": "PRIVATE PROGRESS"}))
        rows[2]["parentUuid"] = "progress-node"
        result = self.parse(rows)
        self.assertEqual([r["id"] for r in result], ["intro", "answer"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_progress_between_response_fragments_is_transparent(self):
        rows = parallel_rows()
        rows.insert(3, entry("progress", "tool-progress", "call-a"))
        rows[4]["parentUuid"] = "tool-progress"
        self.assertEqual([r["id"] for r in self.parse(rows)], ["intro", "answer"])

    def test_unrelated_opaque_metadata_leaves_are_not_conversation_forks(self):
        for kind in ("progress", "attachment", "system"):
            with self.subTest(kind=kind):
                rows = parallel_rows()
                rows.append(entry(kind, "metadata-leaf", "prompt"))
                self.assertEqual([r["id"] for r in self.parse(rows)], ["intro", "answer"])

    def test_progress_cannot_hide_a_genuine_conversation_fork(self):
        rows = parallel_rows()
        rows.extend([entry("progress", "other-progress", "prompt"),
                     entry("assistant", "other-answer", "other-progress", [{"type": "text", "text": "STALE"}], "other-response")])
        with self.assertRaisesRegex(replies.ReplyError, "ambiguous active branch"):
            self.parse(rows)

    def test_opaque_parent_cycles_are_still_rejected(self):
        rows = parallel_rows()
        rows.append(entry("progress", "cyclic-progress", "cyclic-progress"))
        with self.assertRaisesRegex(replies.ReplyError, "parent cycle"):
            self.parse(rows)

    def test_result_arrival_order_does_not_select_a_branch(self):
        rows = parallel_rows()
        rows[4], rows[5] = rows[5], rows[4]
        self.assertEqual([r["id"] for r in self.parse(rows)], ["intro", "answer"])

    def test_foreign_writer_on_a_later_linear_response_is_rejected(self):
        rows = parallel_rows()
        rows[-1]["agentId"] = "foreign-agent"
        with self.assertRaisesRegex(replies.ReplyError, "conversation writers"):
            self.parse(rows)

    def test_tool_id_not_parent_position_identifies_the_call_within_one_response(self):
        rows = parallel_rows()
        rows[4]["parentUuid"] = "call-b"
        self.assertEqual([r["id"] for r in self.parse(rows)], ["intro", "answer"])

    def test_multiple_visible_fragments_keep_their_own_ids_and_order(self):
        rows = parallel_rows()
        rows.insert(8, entry("assistant", "middle", "result-c", [{"type": "text", "text": "More visible text."}],
                             "response-1", apiBlockIndex=4))
        rows[9]["parentUuid"] = "middle"
        self.assertEqual([r["id"] for r in self.parse(rows)], ["intro", "middle", "answer"])
        self.assertEqual([r["text"] for r in self.parse(rows)], ["Before tools.", "More visible text.", "After tools. | é猫"])

    def test_one_result_can_answer_multiple_calls_from_the_same_response(self):
        rows = parallel_rows()
        rows[4]["message"]["content"].extend(rows[5]["message"]["content"])
        rows[4]["parentUuid"] = "call-b"
        del rows[5]
        self.assertEqual([r["id"] for r in self.parse(rows)], ["intro", "answer"])

    def test_response_fragments_must_have_distinct_indices_and_the_same_writer(self):
        for change in ("duplicate-index", "bad-index", "other-writer"):
            with self.subTest(change=change):
                rows = copy.deepcopy(parallel_rows())
                if change == "duplicate-index":
                    rows[3]["apiBlockIndex"] = 1
                elif change == "bad-index":
                    rows[3]["apiBlockIndex"] = True
                else:
                    rows[3]["agentId"] = "another-agent"
                with self.assertRaises(replies.ReplyError):
                    self.parse(rows)

    def test_attachment_and_compaction_links_preserve_visible_history(self):
        rows = parallel_rows()
        rows.extend([
            entry("system", "compact", None, subtype="compact_boundary", logicalParentUuid="answer", isMeta=True),
            entry("user", "compact-summary", "compact", "PRIVATE SUMMARY", isCompactSummary=True),
            entry("assistant", "post-compact", "compact-summary", [{"type": "text", "text": "After compaction."}], "response-3"),
        ])
        self.assertEqual([r["text"] for r in self.parse(rows)], ["Before tools.", "After tools. | é猫", "After compaction."])

    def test_real_fork_after_different_tool_results_is_still_rejected(self):
        rows = parallel_rows()
        rows.append(entry("assistant", "other-answer", "result-b", [{"type": "text", "text": "STALE BRANCH"}], "different-response"))
        rows.append({"type": "last-prompt", "sessionId": SESSION, "leafUuid": "other-answer"})
        with self.assertRaisesRegex(replies.ReplyError, "ambiguous active branch"):
            self.parse(rows)

    def test_same_response_id_cannot_merge_unrelated_branches(self):
        rows = parallel_rows()
        rows.append(entry("assistant", "other-fragment", "prompt", [{"type": "text", "text": "STALE BRANCH"}], "response-1", apiBlockIndex=4))
        with self.assertRaises(replies.ReplyError):
            self.parse(rows)

    def test_unknown_or_duplicate_tool_ids_do_not_exempt_a_fork(self):
        for change in ("unknown-result", "duplicate-call", "duplicate-result", "wrong-parent", "other-writer"):
            with self.subTest(change=change):
                rows = copy.deepcopy(parallel_rows())
                if change == "unknown-result":
                    rows[4]["message"]["content"][0]["tool_use_id"] = "not-a-call"
                elif change == "duplicate-call":
                    rows[3]["message"]["content"][0]["id"] = "tool-a"
                elif change == "duplicate-result":
                    rows[5]["message"]["content"][0]["tool_use_id"] = "tool-a"
                elif change == "wrong-parent":
                    rows[4]["parentUuid"] = "prompt"
                elif change == "other-writer":
                    rows[4]["agentId"] = "another-agent"
                with self.assertRaises(replies.ReplyError):
                    self.parse(rows)

    def test_mixed_parallel_result_context_is_validated_but_not_exported(self):
        rows = parallel_rows()
        rows[4]["message"]["content"].append({"type": "text", "text": "PRIVATE EXTRA CONTEXT"})
        rows[5]["message"]["content"].append({"type": "image", "source": {"type": "base64", "data": "PRIVATE"}})
        result = self.parse(rows)
        self.assertEqual([r["id"] for r in result], ["intro", "answer"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        rows.append(entry("assistant", "other-answer", "result-a", [{"type": "text", "text": "STALE"}], "other-response"))
        with self.assertRaisesRegex(replies.ReplyError, "ambiguous active branch"):
            self.parse(rows)

    def test_mixed_tool_result_blocks_are_validated_on_a_linear_chain(self):
        for change in ("unknown-result", "duplicate-result", "wrong-parent"):
            with self.subTest(change=change):
                original = parallel_rows()
                rows = [original[i] for i in (0, 1, 2, 4, 8, 9)]
                rows[4]["parentUuid"] = "result-a"
                content = rows[3]["message"]["content"]
                content.append({"type": "text", "text": "PRIVATE EXTRA CONTEXT"})
                if change == "unknown-result":
                    content[0]["tool_use_id"] = "not-a-call"
                elif change == "duplicate-result":
                    content.append(copy.deepcopy(content[0]))
                else:
                    rows[3]["parentUuid"] = "prompt"
                with self.assertRaises(replies.ReplyError):
                    self.parse(rows)

    def test_valid_mixed_result_keeps_its_extra_context_out_of_replies(self):
        original = parallel_rows()
        rows = [original[i] for i in (0, 1, 2, 4, 8, 9)]
        rows[4]["parentUuid"] = "result-a"
        rows[3]["message"]["content"].append({"type": "text", "text": "PRIVATE EXTRA CONTEXT"})
        result = self.parse(rows)
        self.assertEqual([r["id"] for r in result], ["intro", "answer"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_forks_through_system_or_attachment_nodes_are_not_hidden(self):
        for kind in ("system", "attachment"):
            with self.subTest(kind=kind):
                rows = parallel_rows()
                rows.extend([entry(kind, "other-context", "result-b"),
                             entry("assistant", "other-answer", "other-context", [{"type": "text", "text": "STALE"}], "other-response")])
                with self.assertRaisesRegex(replies.ReplyError, "ambiguous active branch"):
                    self.parse(rows)

    def test_sidechain_does_not_merge_with_a_foreground_response(self):
        rows = parallel_rows()
        rows.append(entry("assistant", "sidechain", "prompt", [{"type": "text", "text": "PRIVATE SIDECHAIN"}], "response-1", isSidechain=True))
        self.assertNotIn("PRIVATE", json.dumps(self.parse(rows)))

    def test_duplicate_fragment_ids_and_parent_cycles_fail_closed(self):
        for change in ("duplicate-uuid", "cycle", "missing-parent", "two-roots"):
            with self.subTest(change=change):
                rows = copy.deepcopy(parallel_rows())
                if change == "duplicate-uuid":
                    rows.append(copy.deepcopy(rows[1]))
                elif change == "cycle":
                    rows[1]["parentUuid"] = "call-c"
                elif change == "missing-parent":
                    rows[3]["parentUuid"] = "absent"
                else:
                    rows.append(entry("assistant", "other-root", None, [{"type": "text", "text": "STALE"}], "other-response"))
                with self.assertRaises(replies.ReplyError):
                    self.parse(rows)

    def test_exact_binding_cli_and_delivery_validator_accept_parallel_tools(self):
        self.parse(parallel_rows())
        with mock.patch.dict(os.environ, {"REX_ANNOTATION_STATE_DIR": str(Path(self.temp.name) / "state")}):
            replies.register_binding("claude", os.getpid(), "owned-session", "owned-block", SESSION, str(self.path))
            scope = ["--agent", "claude", "--pid", str(os.getpid()), "--session", "owned-session", "--block", "owned-block"]
            for operation in (["replies", *scope], ["validate", *scope, "--conversation", SESSION]):
                result = subprocess.run([sys.executable, str(ROOT / "integrations/session_replies.py"), *operation],
                                        env=os.environ, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value["sessionId"], SESSION)


if __name__ == "__main__":
    unittest.main()
