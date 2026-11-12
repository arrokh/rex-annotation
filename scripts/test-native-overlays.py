#!/usr/bin/env python3
"""Opt-in native reply picker/insert/Send E2E using fake executables, never real agents."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("annotation_live", ROOT / "scripts/test-rex-annotate-live.py")
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)

C_SOURCE = r'''
#include <stdio.h>
#include <termios.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/wait.h>
int main(int argc, char **argv) {
  struct termios settings;
  if (argc != 2 || tcgetattr(0, &settings) != 0) return 2;
  cfmakeraw(&settings);
  if (tcsetattr(0, TCSANOW, &settings) != 0) return 3;
  int file = open(argv[1], O_CREAT|O_TRUNC|O_WRONLY, 0600);
  if (file < 0) return 4;
  const char *python = getenv("REX_TEST_PYTHON");
  const char *hook = getenv("REX_TEST_HOOK");
  const char *payload = getenv("REX_TEST_PAYLOAD");
  const char *transcript = getenv("REX_TEST_TRANSCRIPT");
  if (!python || !hook || !payload || getenv("REX_PID") || getenv("REX_ANNOTATION_ROOT")) return 6;
  int transcript_file = transcript ? open(transcript, O_RDONLY) : -1;
  if (transcript && transcript_file < 0) return 11;
  pid_t child = fork();
  if (child < 0) return 7;
  if (child == 0) {
    int input = open(payload, O_RDONLY);
    if (input < 0 || dup2(input, STDIN_FILENO) < 0) _exit(8);
    close(input);
    execl(python, python, hook, (char *)NULL);
    _exit(9);
  }
  int status;
  if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status) != 0) return 10;
  printf("\033[?2004hSYNTHETIC INPUT READY\r\n"); fflush(stdout);
  unsigned char value;
  while (read(0, &value, 1) == 1) { if (write(file, &value, 1) != 1) return 5; }
  close(file);
  if (transcript_file >= 0) close(transcript_file);
  return 0;
}
'''


CUX_SOURCE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <termios.h>
#include <util.h>
#include <signal.h>
#include <sys/select.h>
#include <sys/wait.h>
int main(int argc, char **argv) {
  if (argc != 3) return 20;
  struct termios settings;
  if (tcgetattr(0, &settings) != 0) return 21;
  cfmakeraw(&settings);
  if (tcsetattr(0, TCSANOW, &settings) != 0) return 22;
  int master;
  pid_t child;
restart:
  child = forkpty(&master, NULL, NULL, NULL);
  if (child < 0) return 23;
  if (child == 0) { execl(argv[1], argv[1], argv[2], (char *)NULL); _exit(24); }
  while (1) {
    fd_set readset;
    FD_ZERO(&readset); FD_SET(0, &readset); FD_SET(master, &readset);
    if (select(master + 1, &readset, NULL, NULL, NULL) < 0) return 25;
    if (FD_ISSET(0, &readset)) {
      unsigned char data[4096]; ssize_t count = read(0, data, sizeof(data));
      if (count <= 0) break;
      if (count == 1 && data[0] == 0x1d) {
        kill(child, SIGTERM); waitpid(child, NULL, 0); close(master);
        printf("\r\nCUX CHILD STOPPED\r\n"); fflush(stdout);
        if (read(0, data, 1) != 1 || data[0] != 'r') return 26;
        goto restart;
      }
      if (write(master, data, count) != count) return 27;
    }
    if (FD_ISSET(master, &readset)) {
      char data[4096]; ssize_t count = read(master, data, sizeof(data));
      if (count <= 0) break;
      if (write(1, data, count) != count) return 28;
    }
  }
  kill(child, SIGTERM); waitpid(child, NULL, 0); close(master);
  return 0;
}
'''


def transcript(agent, path, conversation):
    older = "2026-11-10T00:00:01Z"
    latest = "2026-11-10T01:00:01Z"
    text = "LATEST native reply | é猫"
    if agent == "codex":
        rows = [
            {"type":"session_meta", "payload":{"id":conversation}},
            {"type":"response_item", "timestamp":older, "payload":{"id":"old-private-id", "type":"message", "role":"assistant", "phase":"final_answer", "content":[{"type":"output_text", "text":"OLDER reply"}]}},
            {"type":"response_item", "timestamp":older, "payload":{"type":"message", "role":"assistant", "channel":"analysis", "content":[{"type":"output_text", "text":"HIDDEN THOUGHT"}]}},
            {"type":"response_item", "timestamp":latest, "payload":{"id":"latest-private-id", "type":"message", "role":"assistant", "phase":"final_answer", "content":[{"type":"output_text", "text":text}]}},
        ]
    else:
        rows = [
            {"type":"user", "uuid":"u1", "parentUuid":None, "sessionId":conversation, "timestamp":older, "message":{"role":"user", "content":"USER PRIVATE"}},
            {"type":"assistant", "uuid":"a1", "parentUuid":"u1", "sessionId":conversation, "timestamp":older, "message":{"role":"assistant", "content":[{"type":"text", "text":"OLDER reply"}]}},
            {"type":"user", "uuid":"u2", "parentUuid":"a1", "sessionId":conversation, "timestamp":latest, "message":{"role":"user", "content":"another"}},
            {"type":"assistant", "uuid":"a2", "parentUuid":"u2", "sessionId":conversation, "timestamp":latest, "message":{"role":"assistant", "content":[{"type":"thinking", "thinking":"HIDDEN THOUGHT"}, {"type":"text", "text":text}]}},
        ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    return text


def run():
    sessions = []
    with tempfile.TemporaryDirectory(prefix="rex-native-overlay-") as directory:
        base = Path(directory)
        source_file = base / "fixture.c"
        source_file.write_text(C_SOURCE)
        compiler = shutil.which("cc")
        assert compiler, "A local C compiler is required for fake-agent live tests"
        subprocess.run([compiler, str(source_file), "-o", str(base / "codex")], check=True, capture_output=True, timeout=30)
        shutil.copy2(base / "codex", base / "claude")
        cux_source = base / "cux-fixture.c"
        cux_source.write_text(CUX_SOURCE)
        subprocess.run([compiler, str(cux_source), "-o", str(base / "cux")], check=True, capture_output=True, timeout=30)
        state = base / "state"
        state.mkdir(mode=0o700)
        try:
            for launcher, agent in (("codex", "codex"), ("claude", "claude"), ("cux", "claude")):
                for action in ("s", "S"):
                    columns, rows = (40, 20) if action == "s" else (120, 35)
                    raw = base / (launcher + action + ".bin")
                    conversation = "11111111-2222-4333-8444-555555555555"
                    if agent == "codex":
                        path = base / "codex-home/sessions/2026/11/10" / (
                            "rollout-2026-11-10T00-00-00-" + conversation + ".jsonl")
                        path.parent.mkdir(parents=True, exist_ok=True)
                    else:
                        path = base / (launcher + action + ".jsonl")
                    quote = transcript(agent, path, conversation)
                    payload = base / (launcher + action + "-hook.json")
                    payload.write_text(json.dumps({"hook_event_name":"SessionStart", "source":"startup",
                                                  "session_id":conversation, "transcript_path":str(path)}))
                    command = ["/usr/bin/env", "-u", "REX_PID", "-u", "REX_ANNOTATION_ROOT",
                               "REX_ANNOTATION_STATE_DIR=" + str(state), "PYTHONDONTWRITEBYTECODE=1",
                               "REX_TEST_PYTHON=" + sys.executable, "REX_TEST_HOOK=" + str(ROOT / "integrations" / agent / "hooks/register.py"),
                               "REX_TEST_PAYLOAD=" + str(payload)]
                    if agent == "codex":
                        command.append("REX_TEST_TRANSCRIPT=" + str(path))
                    command += ([str(base / "cux"), str(base / "claude"), str(raw)] if launcher == "cux"
                                else [str(base / agent), str(raw)])
                    created = LIVE.rex("session.create", {"label":"rex-annotation-fake-" + launcher, "initial_windows":[{"layout":{"block":{
                        "flavor":"com.superlogical.terminal.shell", "options":{"shell":"none", "login":False,
                        "command":command, "size":{"columns":columns,"rows":rows}}
                    }}}]})
                    session = created["session_id"]
                    sessions.append(session)
                    block = created["initial_windows"][0]["block_ids"][0]
                    window = created["initial_windows"][0]["window_id"]
                    print("OWNED fake", launcher, action, session, block, flush=True)
                    LIVE.wait_for(session, block, lambda s: "SYNTHETIC INPUT READY" in s)
                    pid = LIVE.terminal(session, block, "process")["foreground"]["pid"]
                    records = [json.loads(record.read_text()) for record in (state / "rex-annotation/reply-bindings").glob("*.json")]
                    matching = [record for record in records if record["pid"] == pid and record["rex_session"] == session and record["rex_block"] == block]
                    assert len(matching) == 1 and matching[0]["conversation_id"] == conversation, records
                    if launcher == "cux":
                        old_child = matching[0]["native_child_pid"]
                        assert old_child != pid
                        if action == "s":
                            LIVE.terminal(session, block, "write", {"data":"\x1d"})
                            LIVE.wait_for(session, block, lambda screen: "CUX CHILD STOPPED" in screen)
                            stale = subprocess.run([sys.executable, str(ROOT / "integrations/session_replies.py"), "replies",
                                "--agent","claude","--pid",str(pid),"--session",session,"--block",block],
                                env=dict(os.environ, REX_ANNOTATION_STATE_DIR=str(state), PYTHONDONTWRITEBYTECODE="1"),
                                capture_output=True, text=True, timeout=5)
                            assert stale.returncode != 0 and "native child" in stale.stderr, stale.stderr
                            event = json.loads(payload.read_text()); event["source"] = "resume"
                            payload.write_text(json.dumps(event))
                            LIVE.terminal(session, block, "write", {"data":"r"})
                            deadline = time.monotonic() + 5
                            while time.monotonic() < deadline:
                                records = [json.loads(record.read_text()) for record in (state / "rex-annotation/reply-bindings").glob("*.json")]
                                matching = [record for record in records if record["pid"] == pid]
                                if matching and matching[0].get("native_child_pid") != old_child: break
                                time.sleep(0.05)
                            assert matching and matching[0]["native_child_pid"] != old_child, records
                            print("PASS CUX child exit fails closed; resumed child rebinds same wrapper and conversation", flush=True)
                    target = {"session_id":session,"block_id":block,"window_id":window}
                    layer = LIVE.rex("session.new_layer", {"session_id":session,"window_id":window,"focus":True,"bounds":[0,0.05,1,0.9],
                        "layout":{"block":{"flavor":"com.superlogical.terminal.shell","options":{"shell":"none","login":False,
                        "command":["/usr/bin/env","REX_ANNOTATION_STATE_DIR=" + str(state),"PYTHONDONTWRITEBYTECODE=1",shutil.which("nvim"),
                            "--noplugin","-u","NONE","-i","NONE","-n","-c",
                            "lua dofile(" + json.dumps(str(ROOT / "rex/annotate_view.lua")) + ").start(vim.json.decode(" + json.dumps(json.dumps(target)) + "))"],
                        "exit":{"on_completion":True,"quick_exit_threshold_ms":0}}}}})
                    overlay = layer["block_ids"][0]
                    LIVE.rex("session.disown_block", {"session_id":session,"block_ids":[overlay]})
                    LIVE.terminal(session, overlay, "resize", {"columns":columns, "rows":rows})
                    actual_size = LIVE.terminal(session, overlay, "size")
                    assert (actual_size["columns"], actual_size["rows"]) == (columns, rows), actual_size
                    heading = "Codex REPLIES" if agent == "codex" else "Claude Code REPLIES"
                    screen = LIVE.wait_for(session, overlay, lambda s: heading in s and "LATEST native reply" in s)
                    assert screen.count(heading) == 1 and "HIDDEN THOUGHT" not in screen and "USER PRIVATE" not in screen, screen
                    assert "private-id" not in screen and "2026-11-10T" not in screen, screen
                    LIVE.terminal(session, overlay, "write", {"data":"\r"})
                    detail = LIVE.wait_for(session, overlay, lambda s: "REPLY" in s and quote in s and "OLDER reply" not in s)
                    for shortcut in ("v/V select", "Enter note", "m edit", "p preview", "y copy", "s insert", "S send now", "q close"):
                        assert shortcut in detail, (columns, rows, shortcut, detail)
                    if os.environ.get("REX_ANNOTATION_EVIDENCE_DIR"):
                        evidence = Path(os.environ["REX_ANNOTATION_EVIDENCE_DIR"])
                        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
                        (evidence / (launcher + "-" + str(columns) + "x" + str(rows) + ".txt")).write_text(detail)
                    LIVE.terminal(session, overlay, "write", {"data":"ggV\rsynthetic note\x13"})
                    LIVE.wait_for(session, overlay, lambda s: "1 notes" in s)
                    if os.environ.get("REX_ANNOTATION_EVIDENCE_DIR"):
                        html = LIVE.terminal(session, overlay, "format", {"format":"html","unwrap":True})["content"]
                        (Path(os.environ["REX_ANNOTATION_EVIDENCE_DIR"]) / (launcher + "-" + str(columns) + "-annotated.html")).write_text(html)
                    LIVE.terminal(session, overlay, "write", {"data":action})
                    if action == "s":
                        LIVE.wait_for(session, overlay, lambda s: "Insert into the ORIGINAL pane?" in s)
                        LIVE.terminal(session, overlay, "write", {"data":"i"})
                    LIVE.wait_until_closed(session, overlay)
                    expected = ("# Terminal annotations\n\n## 1\n> " + quote + "\n\nComment:\nsynthetic note").encode()
                    sent = b"\x1b[200~" + expected + b"\x1b[201~" + (b"\r" if action == "S" else b"")
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and (not raw.exists() or raw.read_bytes() != sent):
                        time.sleep(0.05)
                    assert raw.read_bytes() == sent, (agent, action, raw.read_bytes())
                    view = LIVE.rex("session.view", {"session_id":session})
                    focused = next(w for w in view["windows"] if w["window_id"] == window)["focused_block_id"]
                    assert focused == block, focused
                    print("PASS fake", launcher, action, "automatic hook binding without annotation launcher, exact reply, Enter note, exact payload, auto-close and source focus", flush=True)
        finally:
            failures = []
            for session in sessions:
                try:
                    LIVE.rex("session.destroy", {"session_id":session})
                except Exception as error:
                    failures.append((session,str(error)))
            current = {row["session_id"] for row in LIVE.rex("session.list", {})["sessions"]}
            failures.extend((session,"still present") for session in sessions if session in current)
            assert not failures, failures
            print("PASS cleanup: all owned fake-agent Rex sessions absent", flush=True)


if __name__ == "__main__":
    run()
