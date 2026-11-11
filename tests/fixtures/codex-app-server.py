#!/usr/bin/env python3
"""Synthetic config-only Codex JSONL server. Never starts a coding-agent thread."""
import json
import os
from pathlib import Path
import re
import sys

if sys.argv[1:] not in (["app-server", "--listen", "stdio://"], ["app-server", "--stdio"], ["app-server"]):
    raise SystemExit("fixture only permits an isolated config app-server")

home = Path(os.environ["CODEX_HOME"]).resolve()
home.mkdir(parents=True, exist_ok=True)
store = home / "fixture-setup-state.json"
state = json.loads(store.read_text()) if store.exists() else {"revision": 0, "config": {}}
config = state["config"]
config_file = home / "config.toml"
hook_file = home / "hooks.json"


def version():
    return "sha256:" + format(state["revision"], "064x")


def inventory(cwd):
    settings = json.loads(hook_file.read_text()) if hook_file.exists() else {}
    hooks = []
    for event, groups in settings.get("hooks", {}).items():
        event_key = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
        for group_index, group in enumerate(groups):
            for handler_index, handler in enumerate(group.get("hooks", [])):
                key = str(hook_file) + ":" + event_key + ":" + str(group_index) + ":" + str(handler_index)
                saved = config.get("hooks", {}).get("state", {}).get(key, {})
                current = "sha256:" + format(len(hooks) + 1, "064x")
                trusted = saved.get("trusted_hash")
                hooks.append({
                    "key": key, "eventName": event[0].lower() + event[1:],
                    "handlerType": handler.get("type", "command"), "command": handler.get("command"),
                    "async": handler.get("async", False), "matcher": group.get("matcher"),
                    "timeoutSec": handler.get("timeout", 3 if event == "SessionEnd" else 600),
                    "statusMessage": handler.get("statusMessage"),
                    "additionalContextLimit": handler.get("additionalContextLimit"),
                    "sourcePath": str(hook_file), "source": "user", "pluginId": None,
                    "environmentId": None, "displayOrder": len(hooks),
                    "enabled": saved.get("enabled", True), "isManaged": False,
                    "currentHash": current,
                    "trustStatus": "trusted" if trusted == current else ("modified" if trusted else "untrusted"),
                })
    return {"cwd": cwd, "hooks": hooks, "warnings": [], "errors": []}


def merge(target, value):
    for key, item in value.items():
        if isinstance(item, dict) and isinstance(target.get(key), dict):
            merge(target[key], item)
        else:
            target[key] = item


for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    log = os.environ.get("TEST_CODEX_CALLS")
    if log:
        with open(log, "a") as stream:
            stream.write(json.dumps(request) + "\n")
    if method == "initialized":
        continue
    response = {"id": request.get("id")}
    params = request.get("params", {})
    if method == "initialize":
        result = {"codexHome": str(home), "userAgent": "fixture/0.167.1"}
    elif method == "config/read":
        result = {"config": config, "origins": {}, "layers": [{
            "name": {"type": "user", "file": str(config_file)}, "version": version(),
            "config": config, "disabledReason": None,
        }], "version": version()}
    elif method == "configRequirements/read":
        result = {"requirements": None}
    elif method == "hooks/list":
        result = {"data": [inventory(cwd) for cwd in params.get("cwds", [str(Path.cwd())])]}
    elif method == "config/batchWrite":
        if params.get("expectedVersion") not in (None, version()):
            response["error"] = {"code": -32000, "message": "configuration version conflict"}
            print(json.dumps(response), flush=True)
            continue
        for edit in params["edits"]:
            key, value = edit["keyPath"], edit["value"]
            if edit["mergeStrategy"] != "upsert":
                raise SystemExit("fixture forbids replacement of unrelated configuration")
            if key == "features.hooks":
                config.setdefault("features", {})["hooks"] = value
            elif key == "hooks.state":
                merge(config.setdefault("hooks", {}).setdefault("state", {}), value)
            else:
                raise SystemExit("fixture forbids changing unrelated settings: " + key)
        state["revision"] += 1
        store.write_text(json.dumps(state))
        result = {"status": "ok", "version": version(), "filePath": str(config_file), "overriddenMetadata": None}
    else:
        raise SystemExit("fixture forbids model, authentication, and unknown RPC methods: " + method)
    response["result"] = result
    print(json.dumps(response), flush=True)
