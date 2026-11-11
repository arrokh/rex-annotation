#!/usr/bin/env python3
"""Codex CLI SessionStart/SessionEnd hook adapter."""

import json
import os
import sys
from pathlib import Path

INTEGRATIONS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(INTEGRATIONS))
sys.dont_write_bytecode = True

from session_replies import ReplyError, invalidate_binding, register_binding, unregister_binding  # noqa: E402
from native_scope import rex_scope  # noqa: E402


def _hook_input():
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ReplyError("Codex hook input is oversized")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReplyError("Codex hook input is malformed: {}".format(error))
    if not isinstance(payload, dict):
        raise ReplyError("Codex hook input must be a JSON object")
    return payload


def main():
    if not os.environ.get("REX_SESSION") or not os.environ.get("REX_BLOCK"):
        return 0
    try:
        payload = _hook_input()
        if payload.get("agent_id") or payload.get("agent_type"):
            return 0
        scope = rex_scope("codex")
        if scope is None:
            return 0
        rex_session, rex_block, pid = scope
        event = payload.get("hook_event_name")
        conversation = payload.get("session_id")
        if event in ("SessionStart", "UserPromptSubmit", "Stop"):
            if event in ("SessionStart", "UserPromptSubmit"):
                invalidate_binding("codex", pid, rex_session, rex_block)
            transcript = payload.get("transcript_path")
            if not isinstance(transcript, str) or not transcript:
                raise ReplyError("Codex did not provide transcript_path; enable local session persistence")
            register_binding("codex", pid, rex_session, rex_block, conversation, transcript,
                             allow_pending=event in ("SessionStart", "UserPromptSubmit"))
            return 0
        if event == "SessionEnd":
            if isinstance(conversation, str) and conversation:
                unregister_binding("codex", pid, rex_session, rex_block, conversation)
            return 0
        return 0
    except ReplyError as error:
        print("rex-annotation Codex hook: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
