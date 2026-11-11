#!/usr/bin/env python3
"""Register the exact Codex thread from the documented tool environment."""

import os
import sys
from pathlib import Path

INTEGRATIONS = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(INTEGRATIONS))
sys.dont_write_bytecode = True

import session_replies  # noqa: E402


def main():
    try:
        thread_id = os.environ.get("CODEX_THREAD_ID")
        if not thread_id:
            raise session_replies.ReplyError(
                "Codex did not expose CODEX_THREAD_ID; invoke this skill from a Codex CLI tool shell"
            )
        thread_id = session_replies._require_token(thread_id, "CODEX_THREAD_ID", 128)
        try:
            import uuid

            thread_id = str(uuid.UUID(thread_id))
        except ValueError:
            raise session_replies.ReplyError("CODEX_THREAD_ID must be a Codex UUID")
        rex_session = session_replies._env_token("REX_SESSION")
        rex_block = session_replies._env_token("REX_BLOCK")
        try:
            pid = int(session_replies._env_token("REX_PID"))
        except ValueError:
            raise session_replies.ReplyError("REX_PID must be a positive integer")

        transcript = None
        # Reuse the native SessionStart path only when it is the same exact thread
        # and Rex binding. This also avoids choosing among historical rollouts.
        try:
            _, existing = session_replies._current_binding(pid, "codex", rex_session, rex_block)
            if existing.get("conversation_id") == thread_id:
                session_replies._parse_transcript("codex", existing["transcript_path"], thread_id)
                transcript = existing["transcript_path"]
        except session_replies.ReplyError:
            pass
        if transcript is None:
            transcript = session_replies.find_codex_transcript(thread_id)
        record = session_replies.register_binding(
            "codex", pid, rex_session, rex_block, thread_id, transcript
        )
        print("Registered Codex thread {} for Rex reply selection.".format(record["conversation_id"]))
        return 0
    except session_replies.ReplyError as error:
        print("rex-annotation Codex skill: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
