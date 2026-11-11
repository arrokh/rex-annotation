import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class PluginPackagingTests(unittest.TestCase):
    def test_claude_root_plugin_hook_works_from_a_moved_checkout(self):
        with tempfile.TemporaryDirectory(prefix="rex plugin copy ") as directory:
            copied = Path(directory) / "plugin"
            copied.mkdir()
            for name in ("integrations", "hooks", ".claude-plugin"):
                shutil.copytree(ROOT / name, copied / name, ignore=shutil.ignore_patterns("__pycache__"))
            configuration = json.loads((copied / "hooks/hooks.json").read_text())
            command = configuration["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(copied))
            parts = shlex.split(command)
            parts[0] = sys.executable
            state = Path(directory) / "state"
            payload = {"hook_event_name":"SessionStart", "session_id":"claude-synthetic-1", "source":"startup",
                       "transcript_path":str(copied / "integrations/tests/fixtures/claude_session.jsonl")}
            result = subprocess.run(parts, input=json.dumps(payload), text=True, capture_output=True, timeout=5,
                                    env={**os.environ, "REX_SESSION":"test-session", "REX_BLOCK":"test-block", "REX_PID":str(os.getpid()),
                                         "REX_ANNOTATION_STATE_DIR":str(state), "PYTHONDONTWRITEBYTECODE":"1"})
            self.assertEqual(result.returncode, 0, result.stderr)
            metadata = list((state / "rex-annotation/reply-bindings").glob("*.json"))
            self.assertEqual(len(metadata), 1)
            self.assertEqual(json.loads(metadata[0].read_text())["conversation_id"], "claude-synthetic-1")


if __name__ == "__main__":
    unittest.main()
