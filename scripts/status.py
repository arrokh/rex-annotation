#!/usr/bin/env python3
"""Read-only Rex Annotation setup checks."""
import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent
_CONFIGURED_ROOT = Path(os.environ.get("REX_ANNOTATION_ROOT", "")).expanduser() if os.environ.get("REX_ANNOTATION_ROOT") else None
ROOT = (_CONFIGURED_ROOT if _CONFIGURED_ROOT and _CONFIGURED_ROOT.is_dir()
        and (_CONFIGURED_ROOT / "rex/annotate.lua").is_file() else _DEFAULT_ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _check(name, status, detail, fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def _run(command, timeout=5):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout + result.stderr).strip()
    except subprocess.TimeoutExpired as error:
        parts = [part.decode(errors="replace") if isinstance(part, bytes) else (part or "") for part in (error.stdout, error.stderr)]
        detail = ''.join(parts).strip()
        return None, "timed out after {}s{}".format(timeout, ": " + detail if detail else "")
    except OSError as error:
        return None, str(error)


def _rex_config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))).expanduser() / "rex"


def _loader_matches_root(path):
    if not path.exists():
        return False
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        return False
    if "rex/annotate.lua" not in text or "dofile" not in text:
        return False
    if str(ROOT / "rex/annotate.lua") in text:
        return True
    if 'os.getenv("REX_ANNOTATION_HOME")' in text and '/work/personal/rex-annotation' in text:
        configured = Path(os.environ.get("REX_ANNOTATION_HOME", str(Path.home() / "work/personal/rex-annotation"))).expanduser()
        return configured.resolve() == ROOT.resolve()
    return False


def _has_require(path, module):
    if not path.is_file():
        return False
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        return False
    pattern = re.compile(r"^\s*require\s*\(\s*(['\"])" + re.escape(module) + r"\1\s*\)", re.M)
    return any(pattern.search(line.split("--", 1)[0]) for line in text.splitlines())


def _pi_settings_path(home):
    base = Path(os.environ.get("PI_CODING_AGENT_DIR", str(home / ".pi/agent"))).expanduser()
    return base / "settings.json"


def _path_entry_matches(entry, settings_base):
    if isinstance(entry, str):
        candidate = Path(entry).expanduser()
        if not candidate.is_absolute():
            candidate = settings_base / candidate
        try:
            return Path(os.path.abspath(candidate)).resolve() == ROOT.resolve()
        except OSError:
            return False
    if isinstance(entry, dict):
        for key in ("path", "source", "package"):
            if isinstance(entry.get(key), str) and _path_entry_matches(entry[key], settings_base):
                return True
    return False


def _pi_installed(home):
    settings_path = _pi_settings_path(home)
    if not settings_path.exists():
        return "absent", "Pi settings do not register this checkout", settings_path
    try:
        settings = json.loads(settings_path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        return "invalid", "Cannot read Pi settings: {}".format(error), settings_path
    if not isinstance(settings, dict) or not isinstance(settings.get("packages", []), list):
        return "invalid", "Pi settings have an invalid packages list", settings_path
    registered = [item for item in settings.get("packages", []) if _path_entry_matches(item, settings_path.parent)]
    if not registered:
        return "absent", "Pi settings do not register this exact checkout path", settings_path
    if len(registered) != 1:
        return "invalid", "Duplicate Pi declarations for this checkout; remove ambiguous filters", settings_path
    entry = registered[0]
    if isinstance(entry, dict) and "extensions" in entry:
        patterns = entry["extensions"]
        if not isinstance(patterns, list) or any(not isinstance(pattern, str) for pattern in patterns):
            return "invalid", "Pi extension filters are malformed", settings_path
        wanted = "integrations/pi/extensions/index.js"
        positive = [pattern.lstrip("+").removeprefix("./") for pattern in patterns if not pattern.startswith(("!", "-"))]
        negative = [pattern[1:].removeprefix("./") for pattern in patterns if pattern.startswith(("!", "-"))]
        if not patterns or (positive and not any(fnmatch.fnmatchcase(wanted, pattern) for pattern in positive)) or any(fnmatch.fnmatchcase(wanted, pattern) for pattern in negative):
            return "invalid", "Pi package is registered but its annotation extension is disabled by filters", settings_path
    try:
        manifest = json.loads((ROOT / "package.json").read_text())
        extensions = manifest.get("pi", {}).get("extensions")
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        return "invalid", "Root Pi package manifest is invalid: {}".format(error), settings_path
    expected = "./integrations/pi/extensions/index.js"
    if not isinstance(extensions, list) or expected not in extensions or not (ROOT / expected).is_file():
        return "invalid", "Registered root does not expose the expected Pi extension path", settings_path
    return "installed", "Exact checkout is registered and its Pi extension path is present", settings_path


def _codex_state(home):
    skill = home / ".agents/skills/rex-annotation"
    expected_skill = ROOT / "integrations/codex/skills/rex-annotation"
    skill_ok = skill.is_symlink() and skill.resolve() == expected_skill.resolve()
    skill_exists = skill.exists() or skill.is_symlink()
    hook_file = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser() / "hooks.json"
    hook_ok = False
    hook_stale = False
    malformed = False
    if hook_file.exists():
        try:
            config = json.loads(hook_file.read_text())
            hooks = config.get("hooks") if isinstance(config, dict) else None
            if not isinstance(hooks, dict):
                malformed = True
            else:
                managed = []
                active_events = set()
                for event, groups in hooks.items():
                    if not isinstance(groups, list):
                        malformed = True
                        continue
                    for group in groups:
                        if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                            malformed = True
                            continue
                        for handler in group.get("hooks", []):
                            if not isinstance(handler, dict):
                                malformed = True
                                continue
                            command = handler.get("command")
                            if isinstance(command, str) and handler.get("type") == "command":
                                try:
                                    parts = shlex.split(command)
                                except ValueError:
                                    malformed = True
                                    continue
                                if len(parts) == 2 and parts[1].replace("\\", "/").endswith("/integrations/codex/hooks/register.py"):
                                    managed.append(parts[1])
                                    if Path(parts[0]).name.startswith("python3") and Path(parts[1]) == ROOT / "integrations/codex/hooks/register.py":
                                        active_events.add(event)
                expected_events = set(json.loads((ROOT / "integrations/codex/hooks/hooks.json").read_text())["hooks"])
                hook_ok = bool(managed) and active_events >= expected_events and all(Path(path) == ROOT / "integrations/codex/hooks/register.py" for path in managed)
                hook_stale = bool(managed) and not hook_ok
        except (OSError, json.JSONDecodeError, UnicodeError, KeyError, TypeError):
            malformed = True
    partial = skill_ok or hook_ok or skill_exists or hook_stale or malformed
    if malformed:
        return "invalid", "Codex skill/hooks state is malformed or unreadable", skill, hook_file, partial
    if skill_ok and hook_ok:
        return "installed", "Codex skill symlink and managed hooks point to this checkout", skill, hook_file, True
    if partial:
        return "partial", "Codex skill or hooks are missing, stale, or point elsewhere", skill, hook_file, True
    return "absent", "Codex skill and hooks are not installed for this checkout", skill, hook_file, False


def _claude_settings_path(home):
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or str(home / ".claude")).expanduser()
    return config_dir / "settings.json"


def _is_managed_claude_handler(handler):
    command = handler.get("command") if isinstance(handler, dict) and handler.get("type") == "command" else None
    if not isinstance(command, str):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return (len(parts) == 2 and re.fullmatch(r"python3(?:\.\d+)?", Path(parts[0]).name)
            and parts[1].replace("\\", "/").endswith("/integrations/claude/hooks/register.py"))


def _claude_hooks_state(home):
    settings_file = _claude_settings_path(home)
    if not settings_file.exists():
        return "absent", "Claude settings do not register this checkout's lifecycle hooks", settings_file
    try:
        settings = json.loads(settings_file.read_text())
        template = json.loads((ROOT / "hooks/hooks.json").read_text())
        expected_events = set(template["hooks"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        return "invalid", "Cannot read Claude settings or bundled hook template: {}".format(error), settings_file
    if not isinstance(settings, dict):
        return "invalid", "Claude settings must be a JSON object", settings_file
    for policy in ("disableAllHooks", "allowManagedHooksOnly"):
        if policy in settings and not isinstance(settings[policy], bool):
            return "invalid", "Claude " + policy + " setting is malformed", settings_file
        if settings.get(policy):
            return "blocked", "Claude " + policy + " is true, so local annotation hooks cannot run", settings_file
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return "invalid", "Claude settings have an invalid hooks object", settings_file

    managed_paths = []
    active_events = set()
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            return "invalid", "Claude settings have an invalid hooks list", settings_file
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                return "invalid", "Claude settings have an invalid hook group", settings_file
            for handler in group.get("hooks", []):
                if not isinstance(handler, dict):
                    return "invalid", "Claude settings have an invalid hook handler", settings_file
                if not _is_managed_claude_handler(handler):
                    continue
                try:
                    parts = shlex.split(handler["command"])
                except (KeyError, ValueError):
                    continue
                managed_paths.append(parts[1])
                matches_event = any(group.get("matcher") == expected.get("matcher")
                                    for expected in template["hooks"].get(event, []))
                if (re.fullmatch(r"python3(?:\.\d+)?", Path(parts[0]).name)
                        and Path(parts[1]) == ROOT / "integrations/claude/hooks/register.py"
                        and matches_event):
                    active_events.add(event)

    if not managed_paths:
        return "absent", "Claude settings do not register this checkout's lifecycle hooks", settings_file
    if (active_events >= expected_events
            and all(Path(path) == ROOT / "integrations/claude/hooks/register.py" for path in managed_paths)):
        return "installed", "Complete Claude lifecycle hooks point to this checkout", settings_file
    return "partial", "Claude lifecycle hooks are incomplete or point to an old checkout", settings_file


def collect_status(requested=()):
    home = Path.home()
    requested = set(requested)
    checks = []
    required = set()

    cli = shutil.which("rex-annotation")
    required.add("cli_on_path")
    checks.append(_check("cli_on_path", "ok" if cli else "fail", cli or "rex-annotation is not on PATH",
                         "Run ./bin/rex-annotation install and add ~/.local/bin to PATH" if not cli else ""))
    python3 = shutil.which("python3")
    python_code, _ = _run([python3, "-I", "-c", "import sys;raise SystemExit(0 if sys.version_info >= (3,9) else 1)"], timeout=3) if python3 else (None, "")
    python_ok = python_code == 0 and sys.version_info >= (3, 9)
    required.add("python3")
    checks.append(_check("python3", "ok" if python_ok else "fail",
                         "Python 3.9+ is available" if python_ok else "Python 3.9+ is required on PATH",
                         "Install or expose Python 3.9+ on PATH" if not python_ok else ""))
    for name in sorted(requested):
        executable = shutil.which(name)
        cux = shutil.which("cux") if name == "claude" else None
        if cux:
            detail = (executable + "; CUX launcher: " + cux) if executable else ("Claude via CUX: " + cux)
        else:
            detail = executable or (name + " CLI is missing")
        available = bool(executable or cux)
        fix = ("Install Claude Code or CUX first, or omit --claude" if name == "claude"
               else "Install " + name + " first, or omit its setup flag")
        checks.append(_check(name + "_cli", "ok" if available else "fail", detail, fix if not available else ""))

    rex = shutil.which("rex")
    required.add("rex")
    checks.append(_check("rex", "ok" if rex else "fail",
                         "Rex CLI is available" if rex else "rex was not found on PATH",
                         "Install Rex and ensure its CLI is on PATH" if not rex else ""))

    nvim = shutil.which("nvim")
    required.add("neovim_features")
    feature_command = [nvim, "--headless", "--noplugin", "-u", "NONE", "-i", "NONE", "-n",
                       "-c", 'lua if not vim.system or vim.fn.exists("*getregion") ~= 1 then vim.cmd("cquit 1") else vim.cmd("qa!") end'] if nvim else None
    code, output = _run(feature_command, timeout=5) if feature_command else (None, "nvim was not found on PATH")
    nvim_status = "ok" if code == 0 else "fail"
    checks.append(_check("neovim_features", nvim_status,
                         "Neovim exposes vim.system and getregion" if code == 0 else "Required Neovim feature check failed: " + output,
                         "Install a Neovim build with vim.system and getregion" if code != 0 else ""))

    config = _rex_config_dir()
    loader = config / "rex-annotation.lua"
    required.add("rex_loader")
    loader_ok = _loader_matches_root(loader)
    checks.append(_check("rex_loader", "ok" if loader_ok else "fail",
                         "Canonical loader points to this checkout" if loader_ok else "Canonical Rex loader is missing or does not point to this checkout",
                         "Run rex-annotation install" if not loader_ok else ""))

    init = config / "init.lua"
    required.add("rex_init_reference")
    init_ok = _has_require(init, "rex-annotation")
    checks.append(_check("rex_init_reference", "ok" if init_ok else "fail",
                         'Rex init requires "rex-annotation"' if init_ok else 'Rex init.lua does not require "rex-annotation"',
                         "Run rex-annotation install" if not init_ok else ""))

    required.add("rex_config")
    if rex:
        code, output = _run([rex, "--autostart=false", "config", "check"], timeout=5)
        config_status = "ok" if code == 0 else "fail"
        detail = "Rex configuration check passed" if code == 0 else (output or "Rex configuration check failed")
        fix = "Fix Rex configuration errors, then rerun rex config check" if code != 0 else ""
    else:
        config_status, detail, fix = "unknown", "Cannot run rex config check because Rex is unavailable", "Install Rex first"
    checks.append(_check("rex_config", config_status, detail, fix))
    required.add("rex_action")
    action_status, action_detail = "unknown", "Rex runtime action list is unavailable"
    if rex:
        code, output = _run([rex, "--autostart=false", "--timeout", "3s", "actions", "--json"], timeout=5)
        if code == 0:
            try:
                actions = json.loads(output)["actions"]
                action_status = "ok" if any(action.get("name") == "annotate_open" for action in actions) else "fail"
                action_detail = "Annotation action is registered in the running Rex server" if action_status == "ok" else "Running Rex has no annotation action"
            except (ValueError, KeyError, TypeError, AttributeError):
                action_detail = "Rex returned an invalid action list"
    checks.append(_check("rex_action", action_status, action_detail,
                         "Start Rex, check rex config check, then deliberately reload Rex config" if action_status != "ok" else ""))

    pi_state, pi_detail, pi_path = _pi_installed(home)
    pi_status = {"installed": "ok", "absent": "not-installed", "invalid": "fail"}[pi_state]
    if "pi" in requested or pi_state == "installed":
        required.add("pi_registration")
    if "pi" in requested and pi_status == "not-installed":
        pi_status = "fail"
        pi_detail = "Pi registration was requested but this checkout is absent from settings"
    checks.append(_check("pi_registration", pi_status, pi_detail,
                         "Run rex-annotation install --pi" if pi_status in ("not-installed", "fail") else ""))
    if pi_state == "installed":
        checks.append(_check("pi_runtime", "unknown", "A running Pi process may not have loaded this package yet",
                             "Start a new Pi process or deliberately reload after reviewing session-auth effects"))

    codex_state, codex_detail, skill_path, hook_path, codex_present = _codex_state(home)
    codex_status = {"installed": "ok", "absent": "not-installed", "partial": "fail", "invalid": "fail"}[codex_state]
    if "codex" in requested or codex_present or codex_state == "installed":
        required.add("codex_paths")
    if "codex" in requested and codex_status == "not-installed":
        codex_status = "fail"
        codex_detail = "Codex installation was requested but its skill/hooks are absent"
    elif codex_state == "partial" and "codex" not in requested and not codex_present:
        codex_status = "not-installed"
    checks.append(_check("codex_paths", codex_status, codex_detail,
                         "Run rex-annotation install --codex" if codex_status in ("not-installed", "fail") else ""))
    if codex_state == "installed":
        required.add("codex_trust")
        try:
            from codex_setup import inspect_codex
            trust = inspect_codex(ROOT, home)
            trust_status, trust_detail = trust["status"], trust["detail"]
            if trust_status == "needs-setup":
                trust_status = "fail"
            if trust_status not in ("ok", "fail", "unknown", "blocked"):
                raise ValueError("Codex returned an invalid trust status")
        except (OSError, ValueError, KeyError, TypeError) as error:
            trust_status, trust_detail = "fail", "Cannot verify Codex hook readiness: " + str(error)
        checks.append(_check("codex_trust", trust_status, trust_detail,
                             "Run rex-annotation install to configure and trust its Codex hooks"
                             if trust_status != "ok" else ""))

    manifest = ROOT / ".claude-plugin/plugin.json"
    launcher = ROOT / "bin/rex-annotation"
    try:
        plugin = json.loads(manifest.read_text())
        claude_plugin_ok = (plugin.get("name") == "rex-annotation" and launcher.is_file()
                            and (ROOT / "hooks/hooks.json").is_file())
    except (OSError, json.JSONDecodeError, UnicodeError, AttributeError):
        claude_plugin_ok = False
    checks.append(_check("claude_plugin", "ok" if claude_plugin_ok else "not-installed",
                         "Bundled Claude plugin files are available for the optional explicit launcher; this does not indicate user activation"
                         if claude_plugin_ok else "Bundled Claude plugin files for the optional explicit launcher are incomplete",
                         "Restore the root plugin files if you use the explicit launcher" if not claude_plugin_ok else ""))

    claude_state, claude_detail, claude_settings = _claude_hooks_state(home)
    claude_status = {"installed": "ok", "absent": "not-installed", "partial": "fail",
                     "invalid": "fail", "blocked": "blocked"}[claude_state]
    if "claude" in requested or claude_state != "absent":
        required.add("claude_hooks")
    if "claude" in requested and claude_status == "not-installed":
        claude_status = "fail"
        claude_detail = "Claude lifecycle hooks were requested but are absent from {}".format(claude_settings)
    if claude_state == "blocked":
        claude_fix = "Hook policy in {} blocks local hooks; the installer preserves this policy. Change it yourself only if intended".format(claude_settings)
    elif claude_state == "invalid":
        claude_fix = "Repair the Claude settings JSON/hooks structure, then rerun rex-annotation install --claude"
    elif claude_status in ("not-installed", "fail"):
        claude_fix = "Run rex-annotation install --claude"
    else:
        claude_fix = ""
    checks.append(_check("claude_hooks", claude_status, claude_detail, claude_fix))
    if claude_state == "installed":
        checks.append(_check("claude_runtime", "unknown",
                             "Claude/CUX lifecycle hooks are registered for new sessions; existing processes and managed runtime policy are not inspected",
                             "Use normal claude or cux inside a Rex pane; existing agent processes are not reloaded"))

    required_fail = any(check["status"] == "fail" or
                        (check["name"] in required and check["status"] in ("unknown", "blocked"))
                        for check in checks)
    overall = "fail" if required_fail else ("attention" if any(check["status"] in ("manual", "unknown", "blocked") for check in checks) else "ok")
    return {"overall": overall, "checks": checks}, required_fail


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print stable JSON checks")
    parser.add_argument("--pi", action="store_true", help="require this checkout's Pi registration")
    parser.add_argument("--codex", action="store_true", help="require this checkout's Codex skill/hooks")
    parser.add_argument("--claude", action="store_true", help="require this checkout's automatic Claude lifecycle hooks")
    args = parser.parse_args(argv)
    requested = [name for name in ("pi", "codex", "claude") if getattr(args, name)]
    report, failed = collect_status(requested)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("Rex Annotation setup: {}".format(report["overall"]))
        for check in report["checks"]:
            print("[{status}] {name}: {detail}".format(**check))
            if check["fix"]:
                print("  Fix: " + check["fix"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
