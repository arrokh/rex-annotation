#!/usr/bin/env python3
"""Verify multiline annotation errors in an owned Rex pane, without agent input."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("startup_error_live", ROOT / "scripts/test-rex-annotate-live.py")
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


def run():
    sessions = []
    with tempfile.TemporaryDirectory(prefix="rex-startup-errors-") as directory:
        base = Path(directory)
        fake_rex = base / "rex"
        calls = base / "calls.jsonl"
        fake_rex.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n"
                           + "with Path(" + repr(str(calls)) + ").open('a') as stream:stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
                           + "if 'session.view' in sys.argv:print('{}');sys.exit(0)\n"
                           + "sys.stderr.write('synthetic binding unavailable\\nActivate the exact owning session hook.\\n');sys.exit(4)\n")
        fake_rex.chmod(0o755)
        try:
            for columns, rows in ((40, 20), (120, 35)):
                created = LIVE.rex("session.create", {"label":"rex-startup-error-test", "initial_windows":[{"layout":{"block":{
                    "flavor":"com.superlogical.terminal.shell", "options":{"shell":"none", "login":False,
                        "command":["/bin/sleep", "60"], "exit":{"on_completion":False}}
                }}}]})
                session = created["session_id"]
                sessions.append(session)
                block = created["initial_windows"][0]["block_ids"][0]
                window = created["initial_windows"][0]["window_id"]
                print("OWNED startup error", session, block, flush=True)
                target = {"session_id":session,"block_id":block,"window_id":window}
                command = ["/usr/bin/env", "PATH=" + str(base) + os.pathsep + os.environ["PATH"],
                           "PYTHONDONTWRITEBYTECODE=1", shutil.which("nvim"), "--noplugin", "-u", "NONE", "-i", "NONE", "-n", "-c",
                           "lua dofile(" + json.dumps(str(ROOT / "rex/annotate_view.lua")) + ").start(vim.json.decode("
                           + json.dumps(json.dumps(target)) + "))"]
                layer = LIVE.rex("session.new_layer", {"session_id":session,"window_id":window,"focus":True,"bounds":[0,0,1,1],
                    "layout":{"block":{"flavor":"com.superlogical.terminal.shell","options":{"shell":"none","login":False,
                        "command":command,"exit":{"on_completion":True,"quick_exit_threshold_ms":0}}}}})
                overlay = layer["block_ids"][0]
                LIVE.rex("session.disown_block", {"session_id":session,"block_ids":[overlay]})
                LIVE.terminal(session, overlay, "resize", {"columns":columns,"rows":rows})
                screen = LIVE.wait_for(session, overlay, lambda text: "Press q to close" in text)
                assert "Rex Annotate could not open:" in screen, screen
                assert "synthetic binding unavailable" in screen, screen
                assert "Activate the exact owning session hook." in screen, screen
                assert not any(error in screen for error in ("E5108", "replacement string", "Press ENTER", "stack traceback")), screen
                evidence = os.environ.get("REX_ANNOTATION_EVIDENCE_DIR")
                if evidence:
                    path = Path(evidence)
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                    (path / ("startup-error-" + str(columns) + "x" + str(rows) + ".txt")).write_text(screen)
                LIVE.terminal(session, overlay, "write", {"data":"q"})
                LIVE.wait_until_closed(session, overlay)
                print("PASS multiline original error and q-close at", str(columns) + "x" + str(rows), flush=True)
            recorded = [json.loads(line) for line in calls.read_text().splitlines()]
            assert recorded and all(call[4] in ("com.superlogical.terminal.process", "session.view") for call in recorded), recorded
        finally:
            failures = []
            for session in sessions:
                try:
                    LIVE.rex("session.destroy", {"session_id":session})
                except Exception as error:
                    failures.append((session, str(error)))
            current = {row["session_id"] for row in LIVE.rex("session.list", {})["sessions"]}
            failures.extend((session, "still present") for session in sessions if session in current)
            assert not failures, failures
            print("PASS cleanup: all owned startup-error sessions absent", flush=True)


if __name__ == "__main__":
    run()
