#!/usr/bin/env python3
"""Native hook checks in disposable homes; network denied, no real model requests."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True
ROOT = Path(os.environ.get("REX_ANNOTATION_ROOT", Path(__file__).resolve().parent.parent)).resolve()
SPEC = importlib.util.spec_from_file_location("native_live", ROOT / "scripts/test-rex-annotate-live.py")
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


def run(agents, launcher=False, fresh_codex=False, send_fixture_input=True):
    sessions, results = [], []
    connection = subprocess.run([shutil.which("rex"), "--autostart=false", "whoami", "--json"],
                                capture_output=True, text=True, check=True, timeout=5)
    endpoint = json.loads(connection.stdout)["endpoint"]
    address = urlsplit(endpoint)
    assert address.scheme == "unix" and address.path, "Native startup smoke requires the local Rex Unix socket"
    # Permit only the existing Rex IPC endpoint; all network access stays denied.
    profile = ('(version 1) (allow default) (deny network*) '
               '(allow network-outbound (remote unix-socket (path-literal ' + json.dumps(unquote(address.path)) + ')))')
    with tempfile.TemporaryDirectory(prefix="rex-native-startup-") as directory:
        base = Path(directory)
        try:
            for agent in agents:
                home = base / agent
                home.mkdir(mode=0o700)
                config, state = home / "config", home / "state"
                config.mkdir(mode=0o700)
                executable = shutil.which(agent)
                if not executable:
                    raise AssertionError(agent + " CLI is missing")
                environment = ["PATH=" + os.environ["PATH"], "HOME=" + str(home), "TERM=xterm-256color", "LANG=en_US.UTF-8",
                               "XDG_CONFIG_HOME=" + str(home / ".config"), "TMPDIR=" + str(base), "PYTHONDONTWRITEBYTECODE=1",
                               "REX_ANNOTATION_STATE_DIR=" + str(state), "REX_SERVER=" + endpoint, "NO_COLOR=1"]
                if agent == "claude":
                    (config / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding":True,"theme":"dark",
                        "lastOnboardingVersion":"2.1.322", "customApiKeyResponses":{"approved":["fixture-not-a-real-key"[-20:]],"rejected":[]},
                        "projects":{str(home.resolve()):{"hasTrustDialogAccepted":True,"hasCompletedProjectOnboarding":True}}}))
                    environment += ["CLAUDE_CONFIG_DIR=" + str(config), "ANTHROPIC_API_KEY=fixture-not-a-real-key",
                                    "DISABLE_AUTOUPDATER=1", "DISABLE_NONESSENTIAL_TRAFFIC=1"]
                    options = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "user", "--tools", ""]
                else:
                    (config / "config.toml").write_text('model_provider="fixture"\nmodel="fixture"\ncli_auth_credentials_store="file"\n'
                        '[features]\ndaemon_auto_start=false\n'
                        '[model_providers.fixture]\nname="fixture"\nbase_url="http://127.0.0.1:9/v1"\nenv_key="REX_TEST_KEY"\nwire_api="responses"\n')
                    environment += ["CODEX_HOME=" + str(config), "REX_TEST_KEY=fixture-not-a-real-key"]
                    # Resume synthetic history to test the resume lifecycle event,
                    # unless --fresh-codex requests the exact new-session startup path.
                    resume_id = str(uuid.uuid4())
                    history = config / "sessions/2026/01/02" / ("rollout-2026-01-02T03-04-05-" + resume_id + ".jsonl")
                    if not fresh_codex:
                        history.parent.mkdir(parents=True)
                        entries = [
                            {"timestamp": "2026-01-02T03:04:05.000Z", "type": "session_meta", "payload": {
                                "id": resume_id, "timestamp": "2026-01-02T03:04:05.000Z", "cwd": str(home),
                                "originator": "codex_cli_rs", "cli_version": "0.167.1", "source": "cli",
                                "model_provider": "fixture", "base_instructions": {"text": "Synthetic startup fixture."}}},
                            {"timestamp": "2026-01-02T03:04:06.000Z", "type": "response_item", "payload": {
                                "type": "message", "role": "user", "content": [{"type": "input_text", "text": "Synthetic history only."}]}},
                            {"timestamp": "2026-01-02T03:04:07.000Z", "type": "response_item", "payload": {
                                "type": "message", "role": "assistant", "phase": "final_answer",
                                "content": [{"type": "output_text", "text": "Synthetic saved answer."}]}},
                        ]
                        history.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
                        options = ["--no-alt-screen", "-C", str(home), "resume", resume_id]
                    else:
                        options = ["--no-alt-screen", "-C", str(home)]
                setup_environment = {key:value for key,value in (entry.split("=", 1) for entry in environment)}
                # Shadow Rex only for setup. An unavailable REX_SERVER may fall
                # back to the user's live server, so it is not an isolation boundary.
                setup_commands = home / "setup-bin"
                setup_commands.mkdir()
                setup_rex = setup_commands / "rex"
                setup_rex.write_text("#!" + sys.executable + "\nraise SystemExit(1)\n")
                setup_rex.chmod(0o755)
                setup_environment["PATH"] = str(setup_commands) + os.pathsep + setup_environment["PATH"]
                setup_command = [sys.executable, str(ROOT / "bin/rex-annotation"), "install", "--" + agent]
                # Codex configuration applies its own deny-network sandbox;
                # nesting sandbox-exec is rejected by macOS. Claude setup only
                # writes local JSON, and stays under this outer test sandbox.
                if agent != "codex":
                    setup_command = ["/usr/bin/sandbox-exec", "-p", profile, *setup_command]
                installed = subprocess.run(setup_command, env=setup_environment,
                                           capture_output=True, text=True, timeout=40)
                assert installed.returncode == 0, installed.stderr
                command = ["/bin/sh", "-c", 'exec /usr/bin/env -i "REX_SESSION=$REX_SESSION" "REX_BLOCK=$REX_BLOCK" "$@"', "rex-startup-fixture"]
                native = [shutil.which("python3"), str(ROOT / "bin/rex-annotation"), agent] if launcher else [executable]
                command += environment + ["/usr/bin/sandbox-exec", "-p", profile] + native + options
                created = LIVE.rex("session.create", {"label":"rex-verify-" + agent, "initial_windows":[{"layout":{"block":{
                    "flavor":"com.superlogical.terminal.shell", "options":{"shell":"none","login":False,"command":command,
                    "cwd":str(home),"size":{"columns":120,"rows":35},"exit":{"on_completion":False}}}}}]})
                session = created["session_id"]
                sessions.append(session)
                block = created["initial_windows"][0]["block_ids"][0]
                print("OWNED",agent,session,block,flush=True)
                deadline, screen, record = time.monotonic() + 20, "", None
                fixture_input_at, fixture_submitted, idle_since = None, False, None
                while time.monotonic() < deadline:
                    screen = LIVE.terminal(session,block,"format",{"format":"text","unwrap":True})["content"]
                    # Codex can defer lifecycle hooks until first input. This is
                    # task-only synthetic data for an unreachable fixture model:
                    # all networking is denied and no real credential is present.
                    if agent == "codex" and not send_fixture_input and "Ask Codex to do anything" in screen:
                        if idle_since is None:
                            idle_since = time.monotonic()
                        elif time.monotonic() - idle_since >= 2:
                            break  # Check deferred startup before any user input.
                    if agent == "codex" and send_fixture_input and not fixture_submitted:
                        if fixture_input_at is None and "Ask Codex to do anything" in screen:
                            LIVE.terminal(session, block, "write", {"data": "Offline Rex hook fixture"})
                            fixture_input_at = time.monotonic()
                        elif fixture_input_at is not None and time.monotonic() - fixture_input_at >= 0.6:
                            LIVE.terminal(session, block, "write", {"data": "\r"})
                            fixture_submitted = True
                    if "Hooks need review" in screen:
                        break  # Installer trust must already be complete; never bypass or retry.
                    if "rex-annotation " + agent.title() + " hook:" in screen:
                        break
                    files = list((state / "rex-annotation/reply-bindings").glob("*.json"))
                    if files:
                        assert len(files) == 1
                        record = json.loads(files[0].read_text())
                        break
                    time.sleep(0.1)  # Bounded startup readiness only; no recurring monitor.
                startup_recovered = False
                if not record and agent == "codex" and not send_fixture_input:
                    pid = LIVE.terminal(session,block,"process")["foreground"]["pid"]
                    recovered = subprocess.run(
                        [sys.executable, str(ROOT / "integrations/session_replies.py"), "replies",
                         "--agent", "codex", "--pid", str(pid), "--session", session, "--block", block],
                        env={**os.environ, "CODEX_HOME":str(config), "REX_ANNOTATION_STATE_DIR":str(state),
                             "PYTHONDONTWRITEBYTECODE":"1"}, capture_output=True, text=True, timeout=6)
                    assert recovered.returncode == 0, recovered.stderr
                    snapshot = json.loads(recovered.stdout)
                    assert snapshot["replies"] and snapshot["replies"][0]["text"] == "Synthetic saved answer."
                    files = list((state / "rex-annotation/reply-bindings").glob("*.json"))
                    assert len(files) == 1
                    record = json.loads(files[0].read_text())
                    startup_recovered = True
                    print("PASS Codex deferred-start recovery used the exact open transcript without sending a prompt", flush=True)
                if record:
                    pid = LIVE.terminal(session,block,"process")["foreground"]["pid"]
                    assert record["pid"] == pid and record["rex_session"] == session and record["rex_block"] == block, record
                    source = Path(record["transcript_path"])
                    assert source.resolve().is_relative_to(home.resolve()), "Native transcript escaped the disposable home"
                    seeded = False
                    if not source.exists():
                        # A brand-new native session has no persisted turn. Seed only this
                        # owned test transcript; no user/model message is ever submitted.
                        source.parent.mkdir(parents=True, exist_ok=True)
                        fixture = (ROOT / "integrations/tests/fixtures" / (agent + "_session.jsonl")).read_text()
                        fixture_id = "claude-synthetic-1" if agent == "claude" else "11111111-1111-4111-8111-111111111111"
                        try:
                            with source.open("x") as stream:
                                stream.write(fixture.replace(fixture_id, record["conversation_id"]))
                            seeded = True
                        except FileExistsError:
                            pass
                    validated = subprocess.run([sys.executable,str(ROOT/"integrations/session_replies.py"),"validate",
                        "--agent",agent,"--pid",str(pid),"--session",session,"--block",block,"--conversation",record["conversation_id"]],
                        env={**os.environ,"REX_ANNOTATION_STATE_DIR":str(state),"PYTHONDONTWRITEBYTECODE":"1"},
                        capture_output=True,text=True,timeout=6)
                    assert validated.returncode == 0, validated.stderr
                    result = {"agent":agent,"status":"verified","launch":"launcher" if launcher else "plain-command",
                              "pid":pid,"binding":"exact native lifecycle transcript", "synthetic_transcript_seeded":seeded,
                              "synthetic_resume":agent == "codex" and not fresh_codex,
                              "fresh_startup":agent == "codex" and fresh_codex,
                              "startup_recovered_from_open_transcript":startup_recovered,
                              "offline_fixture_input":fixture_submitted}
                elif "Hooks need review" in screen:
                    raise AssertionError("Automatic Codex setup left hook definitions untrusted:\n" + screen[-2000:])
                else:
                    raise AssertionError(agent + " did not register its SessionStart binding:\n" + screen[-3000:])
                results.append(result)
                print("RESULT",json.dumps(result),flush=True)
        finally:
            failures=[]
            for session in sessions:
                try:LIVE.rex("session.destroy",{"session_id":session})
                except Exception as error:failures.append((session,str(error)))
            current={row["session_id"] for row in LIVE.rex("session.list",{})["sessions"]}
            failures.extend((session,"still present") for session in sessions if session in current)
            assert not failures, failures
            print("PASS cleanup: all owned native-startup Rex sessions absent",flush=True)
    return 0


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent",choices=("claude","codex"))
    parser.add_argument("--launcher", action="store_true", help="check the optional explicit launcher instead of the normal CLI")
    parser.add_argument("--fresh-codex", action="store_true", help="test a plain Codex startup instead of resuming synthetic history")
    parser.add_argument("--no-fixture-input", action="store_true", help="do not submit offline input; isolate SessionStart binding")
    args=parser.parse_args()
    if args.fresh_codex and args.agent != "codex":
        parser.error("--fresh-codex requires --agent codex")
    if args.no_fixture_input and args.fresh_codex:
        parser.error("--no-fixture-input requires a Codex resume with persisted synthetic history")
    raise SystemExit(run([args.agent] if args.agent else ["claude","codex"], args.launcher, args.fresh_codex, not args.no_fixture_input))
