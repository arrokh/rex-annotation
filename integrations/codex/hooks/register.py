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


def _rex_scope():
    names = ("REX_SESSION", "REX_BLOCK", "REX_PID")
    values = [os.environ.get(name) for name in names]
    if not any(name in os.environ for name in names):
        return None
    if not os.environ.get("REX_PID") and not os.environ.get("REX_ANNOTATION_ROOT"):
        return None  # Normal agents outside the opt-in launcher have no binding.
    if not all(values):
        raise ReplyError("Rex hook requires REX_SESSION, REX_BLOCK, and REX_PID")
    try:
        pid = int(values[2])
    except ValueError:
        raise ReplyError("REX_PID must be a positive integer")
    return values[0], values[1], pid


def main():
    try:
        payload = _hook_input()
        scope = _rex_scope()
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
