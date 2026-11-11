#!/usr/bin/env python3
"""Configure and inspect Rex's exact Codex lifecycle-hook trust."""

import json
import os
from pathlib import Path
import re
import selectors
import signal
import shlex
import shutil
import subprocess
import sys
import time

_MIN_CODEX_VERSION = (0, 167, 1)
_RPC_TIMEOUT_SECONDS = 10.0
_MAX_RPC_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_RPC_LINE_BYTES = 512 * 1024
_MAX_RPC_REQUEST_BYTES = 64 * 1024
_UPGRADE = "Upgrade Codex CLI to 0.167.1 or newer with hooks/list and config/batchWrite support."


class CodexSetupError(ValueError):
    """Codex setup could not be completed safely."""


class _ProtocolError(CodexSetupError):
    pass


class _AppServer:
    """A bounded JSONL client for one app-server process started by this helper."""

    def __init__(self, executable, root, home, codex_home):
        environment = os.environ.copy()
        environment["HOME"] = str(home)
        environment["CODEX_HOME"] = str(codex_home)
        # Configuration inspection must not transmit account data or warm remote
        # plugin/model caches. macOS is the supported runtime; fake Linux test
        # executables remain usable without adding a sandbox dependency there.
        for name in ("REX_SESSION", "REX_BLOCK", "REX_PID"):
            environment.pop(name, None)
        command = [executable, "app-server", "--listen", "stdio://"]
        if sys.platform == "darwin":
            sandbox = Path("/usr/bin/sandbox-exec")
            if not sandbox.is_file():
                raise CodexSetupError("macOS sandbox-exec is required for network-isolated Codex configuration.")
            command = [str(sandbox), "-p", "(version 1) (allow default) (deny network*)", *command]
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(root),
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as error:
            raise CodexSetupError("Cannot start the isolated Codex app-server: {}. {}".format(error, _UPGRADE))
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        os.set_blocking(self.process.stdin.fileno(), False)
        self.write_selector = selectors.DefaultSelector()
        self.write_selector.register(self.process.stdin, selectors.EVENT_WRITE)
        self.deadline = time.monotonic() + _RPC_TIMEOUT_SECONDS
        self.output_bytes = 0
        self.buffer = bytearray()
        self.next_id = 1
        self.closed = False
        try:
            result = self.request("initialize", {
                "clientInfo": {"name": "rex-annotation-setup", "title": "Rex Annotation setup", "version": "1.0.0"}
            })
            user_agent = result.get("userAgent") if isinstance(result, dict) else None
            self.version = self._parse_version(user_agent)
            if not _same_path(result.get("codexHome"), codex_home):
                raise CodexSetupError("Codex app-server did not target the requested CODEX_HOME; refusing configuration changes.")
            if self.version < _MIN_CODEX_VERSION:
                raise CodexSetupError("Codex app-server {} is too old. {}".format(user_agent or "(unknown version)", _UPGRADE))
            self.notify("initialized", {})
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _parse_version(user_agent):
        if not isinstance(user_agent, str):
            raise CodexSetupError("Codex app-server did not identify its version. {}".format(_UPGRADE))
        match = re.match(r"^[^/\s]+/(\d+)\.(\d+)\.(\d+)(?:[-+][^\s]*)?", user_agent)
        if not match:
            raise CodexSetupError("Cannot identify Codex app-server version {!r}. {}".format(user_agent[:120], _UPGRADE))
        return tuple(int(part) for part in match.groups())

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _ProtocolError("Codex app-server exceeded the total {:.0f}s setup timeout.".format(_RPC_TIMEOUT_SECONDS))
        return remaining

    def _write(self, value):
        try:
            payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        except (TypeError, ValueError) as error:
            raise _ProtocolError("Cannot encode Codex app-server request: {}".format(error))
        if len(payload) > _MAX_RPC_REQUEST_BYTES:
            raise _ProtocolError("Codex app-server request exceeds the bounded request size.")
        stream = self.process.stdin
        if stream is None:
            raise _ProtocolError("Codex app-server stdin closed unexpectedly.")
        view = memoryview(payload)
        while view:
            self._remaining()
            try:
                written = os.write(stream.fileno(), view)
            except BlockingIOError:
                if not self.write_selector.select(self._remaining()):
                    raise _ProtocolError("Codex app-server timed out accepting a JSONL request.")
                continue
            except (BrokenPipeError, OSError) as error:
                raise _ProtocolError("Codex app-server stopped accepting requests: {}".format(error))
            if written <= 0:
                raise _ProtocolError("Codex app-server stopped accepting requests.")
            view = view[written:]

    def notify(self, method, params):
        self._write({"method": method, "params": params})

    def request(self, method, params):
        request_id = self.next_id
        self.next_id += 1
        self._write({"method": method, "id": request_id, "params": params})
        while True:
            message = self._next_message()
            if not isinstance(message, dict):
                raise _ProtocolError("Codex app-server returned a non-object JSON message.")
            if "id" not in message:
                continue  # Notifications, including lifecycle status, are not request responses.
            if message.get("id") != request_id:
                raise _ProtocolError("Codex app-server returned an unexpected response id.")
            if "error" in message:
                error = message.get("error")
                code = error.get("code") if isinstance(error, dict) else None
                detail = error.get("message") if isinstance(error, dict) else None
                if code == -32601:
                    raise CodexSetupError("Codex app-server does not support {}. {}".format(method, _UPGRADE))
                raise CodexSetupError("Codex app-server {} failed{}{}".format(
                    method,
                    " ({}): ".format(code) if code is not None else ": ",
                    str(detail or "unknown RPC error")[:400],
                ))
            if "result" not in message:
                raise _ProtocolError("Codex app-server response omitted both result and error.")
            return message["result"]

    def _next_message(self):
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                if newline > _MAX_RPC_LINE_BYTES:
                    raise _ProtocolError("Codex app-server emitted an oversized JSONL message.")
                raw = bytes(self.buffer[:newline])
                del self.buffer[:newline + 1]
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise _ProtocolError("Codex app-server emitted malformed JSONL: {}".format(error))
            if len(self.buffer) > _MAX_RPC_LINE_BYTES:
                raise _ProtocolError("Codex app-server emitted an oversized JSONL message.")
            remaining = self._remaining()
            ready = self.selector.select(remaining)
            if not ready:
                raise _ProtocolError("Codex app-server timed out waiting for a JSONL response.")
            try:
                chunk = os.read(self.process.stdout.fileno(), 65536)
            except OSError as error:
                raise _ProtocolError("Cannot read Codex app-server output: {}".format(error))
            if not chunk:
                return self._eof()
            self.output_bytes += len(chunk)
            if self.output_bytes > _MAX_RPC_OUTPUT_BYTES:
                raise _ProtocolError("Codex app-server exceeded the bounded total output size.")
            self.buffer.extend(chunk)

    def _eof(self):
        if self.buffer:
            raise _ProtocolError("Codex app-server closed stdout with an incomplete JSONL message.")
        code = self.process.poll()
        raise _ProtocolError("Codex app-server closed stdout unexpectedly{}.".format(
            " (exit {})".format(code) if code is not None else ""
        ))

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    raise CodexSetupError("Failed to reap owned Codex config process {}; inspect its cleanup before retrying.".format(self.process.pid))
        finally:
            self.selector.close()
            self.write_selector.close()
            for stream in (self.process.stdout, self.process.stderr):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _codex_home(home):
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else (home / ".codex").resolve()


def _expected_hooks(root):
    template_path = root / "integrations/codex/hooks/hooks.json"
    register_path = root / "integrations/codex/hooks/register.py"
    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
        entries = []
        for event, groups in template["hooks"].items():
            if not isinstance(event, str) or not isinstance(groups, list):
                raise ValueError("invalid event declarations")
            codex_event = event[0].lower() + event[1:]
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    raise ValueError("invalid hook group")
                matcher = group.get("matcher")
                for handler in group["hooks"]:
                    if not isinstance(handler, dict) or handler.get("type") != "command":
                        raise ValueError("unsupported hook handler")
                    if not isinstance(handler.get("timeout"), int):
                        raise ValueError("hook timeout is missing")
                    entries.append({
                        "eventName": codex_event,
                        "matcher": matcher,
                        "handlerType": "command",
                        "command": "python3 " + shlex.quote(str(register_path)),
                        "async": False,
                        "timeoutSec": handler["timeout"],
                        "statusMessage": handler.get("statusMessage"),
                        "additionalContextLimit": None,
                        "pluginId": None,
                        "environmentId": None,
                        "isManaged": False,
                    })
        if not entries:
            raise ValueError("no bundled hooks")
        return entries
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise CodexSetupError("Cannot validate the bundled Rex Codex hooks: {}".format(error))


def _read_snapshot(client, root, codex_home):
    config_result = client.request("config/read", {"includeLayers": True, "cwd": str(root)})
    requirements_result = client.request("configRequirements/read", {})
    hooks_result = client.request("hooks/list", {"cwds": [str(root)]})
    if not isinstance(requirements_result, dict):
        raise _ProtocolError("Codex configRequirements/read returned an unsupported response. {}".format(_UPGRADE))
    if not isinstance(config_result, dict) or not isinstance(config_result.get("config"), dict):
        raise _ProtocolError("Codex config/read returned an unsupported response. {}".format(_UPGRADE))
    config = config_result["config"]
    features = config.get("features", {})
    if not isinstance(features, dict):
        raise _ProtocolError("Codex config/read returned malformed feature settings.")
    layers = config_result.get("layers")
    if not isinstance(layers, list):
        raise _ProtocolError("Codex config/read omitted configuration layers. {}".format(_UPGRADE))
    expected_config_file = (codex_home / "config.toml").resolve()
    user_layers = []
    explicitly_disabled = []
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get("name"), dict):
            raise _ProtocolError("Codex config/read returned malformed layer metadata.")
        name = layer["name"]
        layer_config = layer.get("config")
        if not isinstance(layer_config, dict):
            raise _ProtocolError("Codex config/read returned malformed layer values.")
        layer_features = layer_config.get("features", {})
        if not isinstance(layer_features, dict):
            raise _ProtocolError("Codex config/read returned malformed feature layer values.")
        if layer_features.get("hooks") is False:
            explicitly_disabled.append(name.get("type", "configuration layer"))
        if (name.get("type") == "user" and name.get("profile") is None
                and isinstance(name.get("file"), str)
                and Path(name["file"]).expanduser().resolve() == expected_config_file):
            user_layers.append(layer)
    if len(user_layers) != 1:
        raise _ProtocolError("Codex app-server did not identify one default user config layer for {}. {}".format(expected_config_file, _UPGRADE))
    user_version = user_layers[0].get("version")
    if not isinstance(user_version, str) or not user_version:
        raise _ProtocolError("Codex app-server omitted the user config version needed for a safe conditional write.")

    requirements = requirements_result.get("requirements") if isinstance(requirements_result, dict) else None
    if requirements is not None and not isinstance(requirements, dict):
        raise _ProtocolError("Codex configRequirements/read returned malformed policy requirements.")
    if isinstance(requirements, dict):
        hooks_policy = requirements.get("hooks")
        if hooks_policy is not None and not isinstance(hooks_policy, dict):
            raise _ProtocolError("Codex returned malformed hook policy requirements.")
        if isinstance(hooks_policy, dict):
            managed_only = hooks_policy.get("allowManagedHooksOnly")
            if managed_only is not None and not isinstance(managed_only, bool):
                raise _ProtocolError("Codex returned malformed managed-hooks-only policy requirements.")
            if managed_only is True:
                explicitly_disabled.append("managed-hooks-only policy")
        feature_policy = requirements.get("featureRequirements", {})
        if not isinstance(feature_policy, dict):
            raise _ProtocolError("Codex returned malformed feature policy requirements.")
        hook_feature_policy = feature_policy.get("hooks")
        if hook_feature_policy is not None and not isinstance(hook_feature_policy, bool):
            raise _ProtocolError("Codex returned malformed hooks feature policy requirements.")
        if hook_feature_policy is False:
            explicitly_disabled.append("hook feature policy")

    if not isinstance(hooks_result, dict) or not isinstance(hooks_result.get("data"), list) or len(hooks_result["data"]) != 1:
        raise _ProtocolError("Codex hooks/list returned an unsupported inventory. {}".format(_UPGRADE))
    inventory = hooks_result["data"][0]
    if (not isinstance(inventory, dict) or not isinstance(inventory.get("hooks"), list)
            or not _same_path(inventory.get("cwd"), root)):
        raise _ProtocolError("Codex hooks/list returned malformed or mismatched hook metadata.")
    warnings = inventory.get("warnings", [])
    errors = inventory.get("errors", [])
    if not isinstance(warnings, list) or not isinstance(errors, list):
        raise _ProtocolError("Codex hooks/list returned malformed warning/error metadata.")
    if warnings or errors:
        raise CodexSetupError("Codex hooks/list reported inventory warnings/errors; refusing to trust an incomplete hook inventory.")

    feature_enabled = features.get("hooks", False)
    if not isinstance(feature_enabled, bool):
        raise _ProtocolError("Codex config/read returned a non-boolean features.hooks setting.")
    return {
        "feature_enabled": feature_enabled,
        "explicitly_disabled": explicitly_disabled,
        "user_version": user_version,
        "hooks": inventory["hooks"],
    }


def _same_path(value, expected):
    if not isinstance(value, str) or not value:
        return False
    try:
        return Path(value).expanduser().resolve() == expected.resolve()
    except (OSError, RuntimeError):
        return False


def _assess(snapshot, root, codex_home):
    if snapshot["explicitly_disabled"]:
        return {"status": "blocked", "detail": "Codex explicitly disables hooks/features or enforces a managed-hooks-only policy; Rex setup preserves that policy."}

    hook_file = (codex_home / "hooks.json").resolve()
    target_hooks = []
    for hook in snapshot["hooks"]:
        if not isinstance(hook, dict):
            raise CodexSetupError("Codex hooks/list returned a malformed hook entry.")
        if _same_path(hook.get("sourcePath"), hook_file):
            if hook.get("source") != "user":
                raise CodexSetupError("The Rex hook file is not reported as a user-source hook inventory; refusing to trust it.")
            target_hooks.append(hook)

    expected = _expected_hooks(root)
    trusted = []
    missing = []
    for definition in expected:
        matches = [hook for hook in target_hooks
                   if all(hook.get(field) == value for field, value in definition.items())]
        if not matches:
            missing.append(definition["eventName"])
            continue
        if len(matches) != 1:
            raise CodexSetupError("Codex reports ambiguous Rex {} hooks in {}; refusing automatic trust.".format(definition["eventName"], hook_file))
        hook = matches[0]
        key = hook.get("key")
        current_hash = hook.get("currentHash")
        if not isinstance(key, str) or not key or len(key) > 4096 or not isinstance(current_hash, str) or not current_hash or len(current_hash) > 256:
            raise CodexSetupError("Codex omitted a valid native key/currentHash for the Rex {} hook.".format(definition["eventName"]))
        if hook.get("enabled") is not True:
            return {"status": "blocked", "detail": "Codex has explicitly disabled the Rex {} hook; setup will not re-enable it.".format(definition["eventName"])}
        if hook.get("trustStatus") not in ("trusted", "untrusted", "modified"):
            raise CodexSetupError("Codex returned unsupported trust status for the Rex {} hook.".format(definition["eventName"]))
        trusted.append({"key": key, "current_hash": current_hash, "trust_status": hook["trustStatus"]})

    keys = [hook["key"] for hook in trusted]
    if len(set(keys)) != len(keys):
        raise CodexSetupError("Codex assigned an ambiguous native key to multiple Rex hooks; refusing automatic trust.")
    if missing:
        return {"status": "needs-setup", "missing_hooks": True,
                "detail": "Codex is missing exact Rex hooks for {}; install/repair the bundled hooks before automatic trust.".format(", ".join(sorted(set(missing))))}
    if not snapshot["feature_enabled"]:
        detail = "Codex features.hooks is not enabled; setup can enable only this feature in user config."
        status = "needs-setup"
    elif any(hook["trust_status"] != "trusted" for hook in trusted):
        detail = "Exact Rex hooks are present but not all are natively trusted yet."
        status = "needs-setup"
    else:
        detail = "Exact Rex hooks are enabled and natively trusted; Codex hooks feature is enabled."
        status = "ok"
    return {"status": status, "detail": detail, "trusted": trusted, "feature_enabled": snapshot["feature_enabled"], "user_version": snapshot["user_version"]}


def _open_client(root, home, codex_home):
    executable = shutil.which("codex")
    if not executable:
        raise CodexSetupError("Codex CLI was not found on PATH. {}".format(_UPGRADE))
    return _AppServer(executable, home, home, codex_home)


def _paths(root, home):
    # Keep the installed command's stable opt/symlink spelling; resolving it to a
    # versioned Cellar path would no longer match the actual installed hooks.
    root = Path(os.path.abspath(Path(root).expanduser()))
    home = Path(home).expanduser().resolve()
    if not root.is_dir():
        raise CodexSetupError("Codex setup root is not a directory: {}".format(root))
    if not (root / "integrations/codex/hooks/hooks.json").is_file() or not (root / "integrations/codex/hooks/register.py").is_file():
        raise CodexSetupError("Codex setup root does not contain the bundled Rex hooks.")
    codex_home = _codex_home(home)
    return root, home, codex_home


def inspect_codex(root, home):
    """Read native Codex config and hook trust without writing or reloading it."""
    root, home, codex_home = _paths(root, home)
    with _open_client(root, home, codex_home) as client:
        snapshot = _read_snapshot(client, home, codex_home)
    assessment = _assess(snapshot, root, codex_home)
    return {"status": assessment["status"], "detail": assessment["detail"]}


def configure_codex(root, home):
    """Enable the hooks feature and trust only exact Rex-owned Codex hook hashes."""
    root, home, codex_home = _paths(root, home)
    with _open_client(root, home, codex_home) as client:
        snapshot = _read_snapshot(client, home, codex_home)
        assessment = _assess(snapshot, root, codex_home)
        if assessment["status"] == "blocked":
            raise CodexSetupError(assessment["detail"])
        if assessment.get("missing_hooks"):
            raise CodexSetupError(assessment["detail"])

        edits = []
        untrusted = {hook["key"]: {"trusted_hash": hook["current_hash"]}
                     for hook in assessment.get("trusted", []) if hook["trust_status"] != "trusted"}
        if untrusted:
            edits.append({"keyPath": "hooks.state", "value": untrusted, "mergeStrategy": "upsert"})
        if not snapshot["feature_enabled"]:
            edits.append({"keyPath": "features.hooks", "value": True, "mergeStrategy": "upsert"})
        if edits:
            response = client.request("config/batchWrite", {
                "edits": edits,
                "expectedVersion": snapshot["user_version"],
                "reloadUserConfig": True,
            })
            if not isinstance(response, dict) or response.get("status") != "ok" or response.get("overriddenMetadata") is not None:
                raise CodexSetupError("Codex did not confirm the targeted Rex hook/feature config write; refusing to claim success.")
            verified = _read_snapshot(client, home, codex_home)
            final = _assess(verified, root, codex_home)
            if final["status"] != "ok":
                raise CodexSetupError("Codex setup verification failed: {}".format(final["detail"]))
            return {"status": "ok", "detail": "Configured and verified exact Rex Codex hooks and features.hooks."}
        if assessment["status"] != "ok":
            raise CodexSetupError("Codex setup could not reach a verified ready state: {}".format(assessment["detail"]))
        return {"status": "ok", "detail": assessment["detail"]}
