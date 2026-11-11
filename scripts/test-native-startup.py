#!/usr/bin/env python3
"""Opt-in native hook startup checks. Disposable homes, network denied, no prompts."""
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

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("native_live", ROOT / "scripts/test-rex-annotate-live.py")
LIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIVE)


def run(agents):
    sessions, results = [], []
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
                               "REX_ANNOTATION_STATE_DIR=" + str(state), "NO_COLOR=1"]
                if agent == "claude":
                    (config / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding":True,"theme":"dark",
                        "lastOnboardingVersion":"2.1.322", "customApiKeyResponses":{"approved":["fixture-not-a-real-key"[-20:]],"rejected":[]},
                        "projects":{str(home.resolve()):{"hasTrustDialogAccepted":True,"hasCompletedProjectOnboarding":True}}}))
                    environment += ["CLAUDE_CONFIG_DIR=" + str(config), "ANTHROPIC_API_KEY=fixture-not-a-real-key",
                                    "DISABLE_AUTOUPDATER=1", "DISABLE_NONESSENTIAL_TRAFFIC=1"]
                    options = ["--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--setting-sources", "", "--tools", ""]
                else:
                    (config / "config.toml").write_text('model_provider="fixture"\nmodel="fixture"\ncli_auth_credentials_store="file"\n'
                        '[model_providers.fixture]\nname="fixture"\nbase_url="http://127.0.0.1:9/v1"\nenv_key="REX_TEST_KEY"\nwire_api="responses"\n')
                    shutil.copyfile(ROOT / "integrations/codex/hooks/hooks.json", config / "hooks.json")
                    environment += ["CODEX_HOME=" + str(config), "REX_TEST_KEY=fixture-not-a-real-key"]
                    options = ["--no-daemon", "--no-alt-screen", "-C", str(home)]
                command = ["/bin/sh", "-c", 'exec /usr/bin/env -i "REX_SESSION=$REX_SESSION" "REX_BLOCK=$REX_BLOCK" "$@"', "rex-startup-fixture"]
                command += environment + ["/usr/bin/sandbox-exec", "-p", "(version 1) (allow default) (deny network*)",
                                          shutil.which("python3"), str(ROOT / "bin/rex-annotation"), agent] + options
                created = LIVE.rex("session.create", {"label":"rex-verify-" + agent, "initial_windows":[{"layout":{"block":{
                    "flavor":"com.superlogical.terminal.shell", "options":{"shell":"none","login":False,"command":command,
                    "cwd":str(home),"size":{"columns":120,"rows":35},"exit":{"on_completion":False}}}}}]})
                session = created["session_id"]
                sessions.append(session)
                block = created["initial_windows"][0]["block_ids"][0]
                print("OWNED",agent,session,block,flush=True)
                deadline, screen, record = time.monotonic() + 20, "", None
                while time.monotonic() < deadline:
                    screen = LIVE.terminal(session,block,"format",{"format":"text","unwrap":True})["content"]
                    if "Hooks need review" in screen:
                        break  # Human trust gate: no approval or retry is attempted.
                    files = list((state / "rex-annotation/reply-bindings").glob("*.json"))
                    if files:
                        assert len(files) == 1
                        record = json.loads(files[0].read_text())
                        break
                    time.sleep(0.1)  # Bounded startup readiness only; no recurring monitor.
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
                    result = {"agent":agent,"status":"verified","pid":pid,"binding":"exact native SessionStart transcript", "synthetic_transcript_seeded":seeded}
                elif "Hooks need review" in screen:
                    result = {"agent":agent,"status":"needs-approval","next":"Review exact Rex Annotation hooks in Codex /hooks"}
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
    return 2 if any(result["status"]=="needs-approval" for result in results) else 0


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent",choices=("claude","codex"))
    args=parser.parse_args()
    raise SystemExit(run([args.agent] if args.agent else ["claude","codex"]))
