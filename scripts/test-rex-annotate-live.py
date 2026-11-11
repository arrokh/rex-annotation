#!/usr/bin/env python3
"""Opt-in, synthetic Rex integration checks. No agent prompt is ever submitted.

Run: python3 scripts/test-rex-annotate-live.py --agents
Requires macOS sandbox-exec, Rex, and the three installed agent CLIs. Test-only
homes and network denial prevent access to normal agent configuration/auth.
Every created session ID is recorded before further work and deleted in finally.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


sys.dont_write_bytecode = True


def rex(method, args):
    result = subprocess.run(
        ["rex", "--timeout", "5s", "api", "call", method, "-"],
        input=json.dumps(args), capture_output=True, text=True, timeout=8,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def terminal(session, block, method, args=None):
    return rex("com.superlogical.terminal." + method, {
        "session_id": session, "block_id": block, "args": args or {},
    })


def paste(session, block, text):
    rex("block.event", {"session_id": session, "block_id": block,
        "event": {"type": "paste", "payload": {"text": text}}})


def wait_for(session, block, predicate, seconds=12):
    deadline = time.monotonic() + seconds
    last = ""
    while time.monotonic() < deadline:
        last = terminal(session, block, "format", {"format": "text", "unwrap": True})["content"]
        if predicate(last):
            return last
        time.sleep(0.15)  # bounded startup/input readiness, not a background monitor
    raise AssertionError("Timed out waiting for test UI:\n" + last[-5000:])


def wait_until_closed(session, block, seconds=6):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        blocks = rex("session.list_blocks", {"session_id": session})["blocks"]
        if not any(item["block_id"] == block for item in blocks):
            return
        time.sleep(0.1)
    raise AssertionError("Annotation pane did not auto-close:\n" + terminal(session, block, "format")["content"])


def insert_with_plugin(script, target, original, text, pi_session=None):
    args = ["nvim", "--headless", "--noplugin", "-u", "NONE", "-i", "NONE", "-n",
            "-l", str(script), json.dumps(target), json.dumps(original), text]
    if pi_session:
        args.append(pi_session)
    result = subprocess.run(args,
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


def invoke_annotation(root, session, source, installed=False):
    clients = [c for c in rex("client.list", {})["clients"]
               if c.get("info", {}).get("kind") == "app"
               and c.get("info", {}).get("platform") == "macos"
               and c.get("principal", {}).get("transport") == "unix"]
    assert len(clients) == 1, "Overlay smoke needs exactly one local macOS Rex app client"
    command = ["rex", "-C", clients[0]["client_id"], "do"]
    command += ["annotate_open"] if installed else [str(root / "rex/annotate.lua"), "--action", "annotate_open"]
    command += ["-s", session, "-b", source, "--json"]
    return subprocess.run(command,
                          capture_output=True, text=True, timeout=15)


def run_agents(names=("pi", "codex", "claude"), vim_check=False, bridge_check=False):
    sessions = []
    owned_blocks = {}
    with tempfile.TemporaryDirectory(prefix="rex-annotate-test-") as temp:
        base = Path(temp)
        insert = base / "insert.lua"
        core = Path(__file__).resolve().parent.parent / "rex/annotate_core.lua"
        insert.write_text('local core = dofile(' + json.dumps(str(core)) + ')\n' + '''
local target, original = vim.json.decode(arg[1]), vim.json.decode(arg[2])
local function call(method, args)
  local r = vim.system({"rex", "--timeout", "5s", "api", "call", method, "-"},
    {stdin=vim.json.encode(args),text=true,timeout=6000}):wait()
  assert(r.code==0, r.stderr)
  return vim.json.decode(r.stdout)
end
local identity = core.identity(original)
assert(identity, "Unrecognized fixture process")
local pi_insert = arg[4] and function(value)
  return core.pi_request(target, identity.pid, {op="insert",sessionId=arg[4],text=value})
end or nil
core.insert(call, target, identity, arg[3], pi_insert)
''')
        try:
            for name in names:
                home = base / name
                home.mkdir(mode=0o700)
                env = ["/usr/bin/env", "-i", "PATH=" + os.environ["PATH"],
                       "HOME=" + str(home), "TERM=xterm-256color", "LANG=en_US.UTF-8",
                       "TMPDIR=" + temp, "NO_COLOR=1"]
                if name == "pi":
                    entry = Path(os.environ.get("REX_ANNOTATION_PI_ENTRY", ""))
                    assert entry.is_file(), "Set REX_ANNOTATION_PI_ENTRY to Pi's unbundled dist/cli.js for the isolated live test"
                    env += ["PI_CODING_AGENT_DIR=" + str(home / "agent"), "PI_OFFLINE=1",
                            "PI_SKIP_VERSION_CHECK=1", "OPENAI_API_KEY=fixture-not-a-real-key"]
                    command = [shutil.which("node"), str(entry), "--no-extensions", "--no-mcp",
                               "--no-skills", "--no-prompt-templates", "--no-context-files",
                               "--no-tools", "--no-session", "--offline", "--model", "openai/gpt-4o-mini"]
                    if vim_check or bridge_check:
                        root = Path(__file__).resolve().parent.parent
                        fixture = home / "paste-check.ts"
                        fixture.write_text('''
import { writeFileSync } from "node:fs";
export default function(pi) {
  pi.on("session_start", (_, ctx) => {
    const factory = ctx.ui.getEditorComponent();
    ctx.ui.setEditorComponent((...args) => {
      const editor = factory(...args);
      queueMicrotask(() => {
        const payload = "# Terminal annotations\\n\\n## 1\\n> a | b\\n> second\\n\\nComment:\\nhi there";
        let submissions = 0;
        editor.onSubmit = () => { submissions++; };
        editor.setClipboardMirrorPolicy("never");
        editor.setClipboardReadFn(() => payload);
        editor.setText(""); editor.handleInput("\\x1b"); editor.handleInput("p");
        const clipboard = editor.getText();
        editor.setText(""); editor.handleInput("\\x1b[200~" + payload + "\\x1b[201~");
        const normalRawPaste = editor.getText();
        editor.setText(""); editor.handleInput("i");
        editor.handleInput("\\x1b[200~" + payload + "\\x1b[201~");
        const inserted = editor.getText();
        writeFileSync(process.env.REX_ANNOTATE_PASTE_REPORT, JSON.stringify({payload, clipboard, inserted, normalRawPaste, submissions}));
        editor.setText("existing draft\\n"); editor.handleInput("\\x1b");
      });
      return editor;
    });
  });
}
''')
                        env += ["REX_ANNOTATE_PASTE_REPORT=" + str(home / "paste-report.json")]
                        vim_extension = Path(os.environ.get("REX_ANNOTATION_PI_VIM", ""))
                        assert vim_extension.is_file(), "Set REX_ANNOTATION_PI_VIM to a local pi-vim index.ts for this optional check"
                        command += ["-e", str(vim_extension)]
                        if bridge_check:
                            command += ["-e", str(root / "integrations/pi/extensions/index.js")]
                            session_file = home / "history.jsonl"
                            session_file.write_text('\n'.join(json.dumps(row) for row in [
                                {"type": "session", "version": 3, "id": "11111111-2222-4333-8444-555555555555", "cwd": str(home), "timestamp": "2026-11-10T00:00:00Z"},
                                {"type": "message", "id": "first", "parentId": None, "timestamp": "2026-11-10T00:00:01Z", "message": {"role": "user", "content": "EARLIEST ABOVE VIEWPORT | valid pipe\n" + "older history\n" * 180, "timestamp": 1}},
                                {"type": "message", "id": "last", "parentId": "first", "timestamp": "2026-11-10T00:00:02Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "LATEST HISTORY MESSAGE"}], "api": "openai-completions", "provider": "openai", "model": "gpt-4o-mini", "stopReason": "stop", "timestamp": 2, "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}}},
                            ]) + '\n')
                            command.remove("--no-session")
                            command += ["--session", str(session_file)]
                        command += ["-e", str(fixture)]
                    ready = lambda s: "gpt-4o-mini" in s
                elif name == "codex":
                    config = home / "codex"
                    config.mkdir()
                    (config / "config.toml").write_text(
                        'model_provider="fixture"\nmodel="fixture"\ncli_auth_credentials_store="file"\n'
                        '[model_providers.fixture]\nname="fixture"\n'
                        'base_url="http://127.0.0.1:9/v1"\nenv_key="REX_ANNOTATE_TEST_KEY"\nwire_api="responses"\n')
                    env += ["CODEX_HOME=" + str(config), "REX_ANNOTATE_TEST_KEY=fixture-not-a-real-key"]
                    command = [shutil.which("codex"), "--no-daemon", "--no-alt-screen", "-C", str(home)]
                    ready = lambda s: "fixture" in s and "Ask Codex" in s
                else:
                    config = home / "claude"
                    config.mkdir()
                    (config / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True,
                        "lastOnboardingVersion": "2.1.322", "theme": "dark",
                        "customApiKeyResponses": {"approved": ["fixture-not-a-real-key"[-20:]], "rejected": []},
                        "projects": {str(home.resolve()): {"hasTrustDialogAccepted": True,
                                                            "hasCompletedProjectOnboarding": True}}}))
                    env += ["CLAUDE_CONFIG_DIR=" + str(home / "claude"),
                            "ANTHROPIC_API_KEY=fixture-not-a-real-key", "DISABLE_AUTOUPDATER=1",
                            "DISABLE_NONESSENTIAL_TRAFFIC=1"]
                    command = [shutil.which("claude"), "--bare", "--safe-mode",
                               "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                               "--setting-sources", "", "--tools", ""]
                    ready = lambda s: "Claude Code v" in s and "\n❯" in s and "Enter to confirm" not in s
                policy = "(version 1) (allow default) (deny network*)"
                if bridge_check:
                    policy += " (allow network* (local unix-socket) (remote unix-socket))"
                command = ["/bin/sh", "-c", 'exec /usr/bin/env -i "REX_SESSION=$REX_SESSION" "REX_BLOCK=$REX_BLOCK" "$@"',
                           "rex-fixture"] + env[2:] + ["/usr/bin/sandbox-exec", "-p",
                                 policy] + command
                created = rex("session.create", {"label": "rex-annotate-test-" + name,
                    "initial_windows": [{"layout": {"block": {"flavor": "com.superlogical.terminal.shell",
                        "options": {"shell": "none", "login": False, "command": command, "cwd": str(home),
                                    "size": {"columns": 120, "rows": 35},
                                    "exit": {"on_completion": False}}}}}]})
                session = created["session_id"]
                sessions.append(session)
                block = created["initial_windows"][0]["block_ids"][0]
                owned_blocks[session] = block
                print("OWNED", name, session, block, flush=True)
                try:
                    wait_for(session, block, ready, seconds=30 if name == "claude" else 12)
                except Exception:
                    print("STARTUP STATE", name, json.dumps(terminal(session, block, "process")), flush=True)
                    raise
                if vim_check or bridge_check:
                    report_file = home / "paste-report.json"
                    deadline = time.monotonic() + 3
                    while not report_file.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    report = json.loads(report_file.read_text())
                    assert report["submissions"] == 0, report
                    assert report["clipboard"] == report["payload"], report
                    assert report["inserted"] == report["payload"], report
                    assert report["normalRawPaste"] == "", report
                    print("PASS Pi-vim p/insert paste preserve newlines; normal mode discards raw paste (requires editor bridge)", flush=True)
                    if bridge_check:
                        identity = terminal(session, block, "process")
                        request = base / "request.lua"
                        request.write_text('local core=dofile(' + json.dumps(str(core)) + ')\n'
                            + 'local target=vim.json.decode(arg[1]); local pid=tonumber(arg[2])\n'
                            + 'io.write(vim.json.encode({snapshot=core.pi_request(target,pid,{op="snapshot"}),'
                            + 'replies=core.pi_request(target,pid,{op="replies"}).replies}))')
                        target = {"session_id": session, "block_id": block}
                        result = subprocess.run(["nvim", "--headless", "--noplugin", "-u", "NONE", "-i", "NONE", "-n", "-l", str(request),
                            json.dumps(target), str(identity["foreground"]["pid"])], capture_output=True, text=True, timeout=8)
                        assert result.returncode == 0, result.stderr
                        history = json.loads(result.stdout)
                        snapshot, replies = history["snapshot"], history["replies"]
                        assert "EARLIEST ABOVE VIEWPORT | valid pipe" in snapshot["text"], snapshot
                        assert "LATEST HISTORY MESSAGE" in snapshot["text"] and "│" not in snapshot["text"], snapshot
                        assert replies[-1]["text"] == "LATEST HISTORY MESSAGE", replies
                        assert all("EARLIEST ABOVE VIEWPORT" not in reply["text"] for reply in replies), replies
                        insert_with_plugin(insert, target, identity, report["payload"], snapshot["sessionId"])
                        wait_for(session, block, lambda s: "hi there" in s)
                        print("PASS exact-session Pi history includes top/offscreen text without UI pipes; editor insert preserves payload in normal Vim mode", flush=True)
                        opened = invoke_annotation(root, session, block)
                        assert opened.returncode == 0, opened.stderr
                        overlay = json.loads(opened.stdout)["block_ids"][0]
                        print("OWNED Pi annotation overlay", overlay, flush=True)
                        picker_screen = wait_for(session, overlay, lambda s: "PI REPLIES" in s and "LATEST HISTORY MESSAGE" in s)
                        assert picker_screen.count("PI REPLIES") == 1, picker_screen
                        assert "[last]" not in picker_screen and "2026-11-10T" not in picker_screen, picker_screen
                        terminal(session, overlay, "write", {"data": "\r"})
                        wait_for(session, overlay, lambda s: "PI REPLY" in s and "LATEST HISTORY MESSAGE" in s)
                        terminal(session, overlay, "write", {"data": "ggV\rbridge-end-to-end-note\x13"})
                        wait_for(session, overlay, lambda s: "bridge-end-to-end-note" in s)
                        terminal(session, overlay, "write", {"data": "s"})
                        wait_for(session, block, lambda s: "bridge-end-to-end-note" in s)
                        wait_until_closed(session, overlay)
                        print("PASS Pi reply flow: one title, relative-time row, Enter comment, direct insert and auto-close without submission", flush=True)
                    continue
                modes = terminal(session, block, "modes")
                assert any(m["number"] == 2004 and m["set"] for m in modes["modes"]), modes
                paste(session, block, "existing-draft ")
                wait_for(session, block, lambda s: "existing-draft" in s)
                identity = terminal(session, block, "process")
                insert_with_plugin(insert, {"session_id": session, "block_id": block}, identity,
                                   "annotation-first\nannotation-second")
                wait_for(session, block, lambda s: "annotation-second" in s)
                paste(session, block, "-editable")
                rendered = wait_for(session, block, lambda s: "annotation-second-editable" in s)
                assert "existing-draft" in rendered and "annotation-first" in rendered, rendered
                print("IDENTITY", name, json.dumps(identity), flush=True)
                print("PASS", name, "plugin insertion stayed editable beside existing draft (no Return sent)", flush=True)
        finally:
            failures = []
            for session in sessions:
                socket = None
                if bridge_check:
                    try:
                        pid = terminal(session, owned_blocks[session], "process")["foreground"]["pid"]
                        socket = Path(f"/tmp/rex-annotate-pi-{os.getuid()}/{pid}.sock")
                    except Exception:
                        pass
                try:
                    rex("session.destroy", {"session_id": session})
                    if socket and socket.exists():
                        if socket.is_socket() and socket.lstat().st_uid == os.getuid():
                            socket.unlink()  # Owned test PID, after its terminal/process was destroyed.
                        assert not socket.exists(), f"Owned test socket remains: {socket}"
                except Exception as error:
                    failures.append((session, str(error)))
            live = {s["session_id"] for s in rex("session.list", {})["sessions"]}
            failures += [(s, "still present") for s in sessions if s in live]
            if failures:
                raise RuntimeError("Cleanup failures: " + repr(failures))
            print("PASS cleanup: all owned Rex sessions absent", flush=True)


def run_overlay(clipboard=False, installed=False, leave_focus=False):
    root = Path(__file__).resolve().parent.parent
    session = None
    if clipboard:
        assert os.environ.get("REX_ANNOTATE_CLIPBOARD_TOKEN"), "Use the Swift clipboard-preserving wrapper"
    try:
        fixture = {"block": {"flavor": "com.superlogical.terminal.shell", "options": {
            "shell": "none", "login": False,
            "command": ["/usr/bin/env", "python3", "-u", "-c",
                        "import signal; print('alpha beta\\nneedle line\\né猫 end'); signal.pause()"],
            "size": {"columns": 120, "rows": 35},
        }}}
        created = rex("session.create", {"label": "rex-annotate-test-overlay", "initial_windows": [{
            "layout": {"split": {"direction": "horizontal", "ratio": 0.375,
                                 "before": fixture, "after": fixture}}}]})
        session = created["session_id"]
        source = created["initial_windows"][0]["block_ids"][0]
        window = created["initial_windows"][0]["window_id"]
        other = created["initial_windows"][0]["block_ids"][1]
        print("OWNED overlay", session, source, other, flush=True)
        wait_for(session, source, lambda s: "alpha beta" in s)
        # CLI/key context can target a pane other than the server's last-focused pane.
        rex("session.focus_block", {"session_id": session, "block_id": other})
        regressions = []
        opened = invoke_annotation(root, session, source, installed)
        assert opened.returncode == 0, opened.stderr
        layer = json.loads(opened.stdout)
        block = layer["block_ids"][0]
        print("OWNED layer", layer["layer_id"], block, flush=True)
        opened_view = rex("session.view", {"session_id": session})
        opened_window = next(w for w in opened_view["windows"] if w["window_id"] == window)
        overlay = next(item for item in opened_window["layers"] if item["layer_id"] == layer["layer_id"])
        source_rect = opened_window["layers"][0]["layout"]["split"]["before"]["rect"]
        bounds = overlay["bounds"]
        if abs(bounds[2] - source_rect[2]) > 1e-9 or abs(bounds[0] - (1 - bounds[2]) / 2) > 1e-9 or abs(bounds[1] - (1 - bounds[3]) / 2) > 1e-9:
            regressions.append(f"Overlay {bounds} must be centered and retain target width {source_rect[2]}")
        wait_for(session, block, lambda s: "SNAPSHOT" in s and "alpha beta" in s)
        duplicate = invoke_annotation(root, session, source, installed)
        assert duplicate.returncode != 0 and "already has an annotation view" in duplicate.stderr
        comment = "why?\\nclarify"  # expected content, not a shell command
        if clipboard:
            comment += " " + os.environ["REX_ANNOTATE_CLIPBOARD_TOKEN"]
        terminal(session, block, "write", {"data": "gg0v4l\r" + comment.replace("\\n", "\r") + "\x13"})
        wait_for(session, block, lambda s: "why? clarify" in s)
        terminal(session, block, "write", {"data": "p"})
        wait_for(session, block, lambda s: "# Terminal annotations" in s and "Comment:" in s)
        if clipboard:
            terminal(session, block, "write", {"data": "y"})
            wait_for(session, block, lambda s: "Copied annotations" in s)
            copied = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True, timeout=3)
            expected = "# Terminal annotations\n\n## 1\n> alpha\n\nComment:\n" + comment.replace("\\n", "\n")
            assert copied.stdout == expected, "Clipboard differs from preview payload"
        terminal(session, block, "write", {"data": "q"})  # back from preview
        if leave_focus:
            # Simulate the user deliberately choosing a different pane before exit.
            rex("session.focus_block", {"session_id": session, "block_id": other})
        terminal(session, block, "write", {"data": "q"})  # quit or discard prompt
        if not clipboard:
            wait_for(session, block, lambda s: "Discard unfinished annotations?" in s)
            terminal(session, block, "write", {"data": "d"})
        wait_until_closed(session, block)
        view = rex("session.view", {"session_id": session})
        current = next(w for w in view["windows"] if w["window_id"] == window)
        expected_focus = other if leave_focus else source
        if current["focused_block_id"] != expected_focus:
            regressions.append(f"Focus returned to {current['focused_block_id']}, expected {expected_focus} (target unless user moved)")
        assert "alpha beta" in terminal(session, source, "format")["content"]
        assert not regressions, "\n".join(regressions)
        print("PASS split overlay: target width/alignment, annotation, preview, repeat guard, close, and correct focus", flush=True)
    finally:
        if session:
            rex("session.destroy", {"session_id": session})
            assert session not in {s["session_id"] for s in rex("session.list", {})["sessions"]}
            print("PASS cleanup: overlay test session absent", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", action="store_true")
    parser.add_argument("--pi-vim", action="store_true", help="check exact paste parity with the actual Pi-vim editor")
    parser.add_argument("--pi-bridge", action="store_true", help="check active-branch reply picking and normal-mode editor insertion")
    parser.add_argument("--overlay", action="store_true")
    parser.add_argument("--clipboard", action="store_true")
    parser.add_argument("--installed", action="store_true", help="test the reloaded config action instead of the script")
    parser.add_argument("--leave-focus", action="store_true", help="verify exit preserves an intentional focus change")
    parser.add_argument("--only", choices=("pi", "codex", "claude"))
    args = parser.parse_args()
    if not (args.agents or args.overlay or args.pi_vim or args.pi_bridge):
        parser.error("choose --agents, --pi-vim, --pi-bridge, and/or --overlay")
    if args.agents or args.pi_vim or args.pi_bridge:
        run_agents(("pi",) if (args.pi_vim or args.pi_bridge) else ((args.only,) if args.only else ("pi", "codex", "claude")), args.pi_vim, args.pi_bridge)
    if args.overlay:
        run_overlay(args.clipboard, args.installed, args.leave_focus)
