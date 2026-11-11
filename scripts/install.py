#!/usr/bin/env python3
"""Install Rex Annotation's local loader and explicitly selected agent integrations."""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent
_CONFIGURED_ROOT = Path(os.environ.get("REX_ANNOTATION_ROOT", "")).expanduser() if os.environ.get("REX_ANNOTATION_ROOT") else None
ROOT = (_CONFIGURED_ROOT if _CONFIGURED_ROOT and _CONFIGURED_ROOT.is_dir()
        and (_CONFIGURED_ROOT / "rex/annotate.lua").is_file() else _DEFAULT_ROOT)
CANONICAL_REQUIRE = 'require("rex-annotation")'
OLD_REQUIRE = re.compile(r"^\s*require\s*\(\s*(['\"])rex_annotation\1\s*\)\s*(?:--.*)?$")
ANNOTATE_REQUIRE = re.compile(r"^\s*require\s*\(\s*(['\"])annotate\1\s*\)\s*(?:--.*)?$")
CANONICAL_REQUIRE_RE = re.compile(r"^\s*require\s*\(\s*(['\"])rex-annotation\1\s*\)\s*(?:--.*)?$")


def lua_string(value):
    delimiter = ""
    while "]" + delimiter + "]" in value:
        delimiter += "="
    return "[" + delimiter + "[" + value + "]" + delimiter + "]"


def _owned_loader(path):
    if not path.exists() or path.is_symlink():
        return False
    try:
        text = path.read_text()
    except (OSError, UnicodeError):
        return False
    return (text.startswith("-- Installed by rex-annotation; only the repository path lives here.\n")
            and "return dofile(" in text and "/rex/annotate.lua" in text)


def _consumer_points_here(consumer, home):
    if not consumer.is_file():
        return False
    try:
        text = consumer.read_text()
    except (OSError, UnicodeError):
        return False
    if "rex-annotation" not in text or "rex/annotate.lua" not in text:
        return False
    if str(ROOT / "rex/annotate.lua") in text and "dofile" in text:
        return True
    if ('os.getenv("REX_ANNOTATION_HOME")' not in text and "os.getenv('REX_ANNOTATION_HOME')" not in text) or '/work/personal/rex-annotation' not in text:
        return False
    configured = Path(os.environ.get("REX_ANNOTATION_HOME", str(home / "work/personal/rex-annotation"))).expanduser()
    return configured.resolve() == ROOT.resolve()


def plan_rex(home):
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))).expanduser() / "rex"
    init = config / "init.lua"
    text = init.read_text() if init.is_file() else ""
    canonical = config / "rex-annotation.lua"
    legacy = config / "rex_annotation.lua"
    consumer = config / "annotate.lua"
    content = ("-- Installed by rex-annotation; only the repository path lives here.\n"
               "return dofile(" + lua_string(str(ROOT / "rex/annotate.lua")) + ")\n")

    if canonical.is_symlink():
        try:
            linked_content = canonical.read_text()
        except (OSError, UnicodeError):
            linked_content = ""
        linked_loader = _consumer_points_here(canonical, home)
        if not linked_loader:
            raise ValueError(f"Refusing to overwrite unrelated symlink {canonical}; no files changed")
    elif canonical.exists() and not _owned_loader(canonical) and canonical.read_text() != content:
        raise ValueError(f"Refusing to overwrite {canonical}; move it yourself or load the project manually")
    if legacy.exists() and not _owned_loader(legacy):
        if any(OLD_REQUIRE.match(line) for line in text.splitlines()):
            raise ValueError(f"Refusing to migrate unknown legacy loader {legacy}; no files changed")
    annotate_references = [line for line in text.splitlines() if ANNOTATE_REQUIRE.match(line)]
    migrate_consumer = bool(annotate_references)
    if migrate_consumer and not _consumer_points_here(consumer, home):
        raise ValueError(f"Consumer-managed loader {consumer} does not point at this checkout. "
                         f"Set REX_ANNOTATION_HOME={ROOT} to migrate its init reference; no files changed")

    lines = text.splitlines()
    updated_lines = []
    inserted = False
    for line in lines:
        if OLD_REQUIRE.match(line) or (migrate_consumer and ANNOTATE_REQUIRE.match(line)):
            if not inserted:
                updated_lines.append(CANONICAL_REQUIRE + " -- rex-annotation")
                inserted = True
            continue
        if CANONICAL_REQUIRE_RE.match(line):
            if not inserted:
                updated_lines.append(line)
                inserted = True
            continue
        updated_lines.append(line)
    if not inserted:
        updated_lines.append(CANONICAL_REQUIRE + " -- rex-annotation")
    updated = "\n".join(updated_lines).rstrip() + "\n"
    plan = []
    if not canonical.exists() or (not canonical.is_symlink() and canonical.read_text() != content):
        plan.append(("file", canonical, content))
    if not init.exists() or init.read_text() != updated:
        plan.append(("file", init, updated))
    return plan


def _is_managed_codex_handler(handler):
    command = handler.get("command") if isinstance(handler, dict) and handler.get("type") == "command" else None
    if not isinstance(command, str):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return len(parts) == 2 and Path(parts[0]).name.startswith("python3") and parts[1].replace("\\", "/").endswith("/integrations/codex/hooks/register.py")


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


def plan_claude(home):
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or str(home / ".claude")).expanduser()
    settings_file = config_dir / "settings.json"
    try:
        config = json.loads(settings_file.read_text()) if settings_file.exists() else {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid Claude settings file {settings_file}: {error}; no files changed")
    if not isinstance(config, dict):
        raise ValueError(f"Invalid Claude settings object in {settings_file}; no files changed")
    if "disableAllHooks" in config and not isinstance(config["disableAllHooks"], bool):
        raise ValueError(f"Invalid disableAllHooks setting in {settings_file}; no files changed")
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Invalid hooks object in {settings_file}; no files changed")
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise ValueError(f"Invalid hooks list for {event!r} in {settings_file}; no files changed")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError(f"Invalid hook group for {event} in {settings_file}; no files changed")
            if any(not isinstance(handler, dict) for handler in group.get("hooks", [])):
                raise ValueError(f"Invalid hook handler for {event} in {settings_file}; no files changed")

    try:
        bundled = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"Invalid bundled Claude hook template: {error}")
    if not isinstance(bundled, dict):
        raise ValueError("Invalid bundled Claude hook template: hooks must be an object")

    command = "python3 " + shlex.quote(str(ROOT / "integrations/claude/hooks/register.py"))
    hooks = config.setdefault("hooks", {})
    for event, groups in list(hooks.items()):
        kept = []
        for original in groups:
            handlers = original.get("hooks", [])
            remaining = [handler for handler in handlers if not _is_managed_claude_handler(handler)]
            if len(remaining) != len(handlers):
                if not remaining:
                    continue
                original = dict(original, hooks=remaining)
            kept.append(original)
        hooks[event] = kept
    for event, groups in bundled.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise ValueError("Invalid bundled Claude hook template: malformed event groups")
        existing = hooks.setdefault(event, [])
        for original in groups:
            group = json.loads(json.dumps(original))
            for handler in group["hooks"]:
                handler["command"] = command
            existing.append(group)
    content = json.dumps(config, indent=2) + "\n"
    if settings_file.exists() and settings_file.read_text() == content:
        return []
    return [("file", settings_file, content)]


def plan_codex(home):
    skills = list((ROOT / "integrations/codex").glob("**/SKILL.md"))
    if len(skills) != 1:
        raise ValueError("Expected one bundled Codex skill")
    source = skills[0].parent
    link = home / ".agents/skills/rex-annotation"
    plan = []
    if not (link.is_symlink() and link.resolve() == source.resolve()):
        if link.exists() or link.is_symlink():
            raise ValueError(f"Refusing to overwrite {link}; remove or move it yourself first")
        plan.append(("link", link, source))

    hook_file = Path(os.environ.get("CODEX_HOME", str(home / ".codex"))).expanduser() / "hooks.json"
    try:
        config = json.loads(hook_file.read_text()) if hook_file.exists() else {}
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid hooks file {hook_file}: {error}; no files changed")
    if not isinstance(config, dict) or not isinstance(config.get("hooks", {}), dict):
        raise ValueError(f"Invalid hooks object in {hook_file}; no files changed")
    hooks = config.setdefault("hooks", {})
    for event, groups in hooks.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise ValueError(f"Invalid hooks list for {event!r} in {hook_file}; no files changed")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks", []), list):
                raise ValueError(f"Invalid hook group for {event} in {hook_file}; no files changed")
            if any(not isinstance(handler, dict) for handler in group.get("hooks", [])):
                raise ValueError(f"Invalid hook handler for {event} in {hook_file}; no files changed")

    bundled = json.loads((ROOT / "integrations/codex/hooks/hooks.json").read_text())["hooks"]
    command = "python3 " + shlex.quote(str(ROOT / "integrations/codex/hooks/register.py"))
    # Remove only handlers owned by this integration, including obsolete checkout paths.
    for event, groups in list(hooks.items()):
        kept_groups = []
        for group in groups:
            group = dict(group)
            remaining = [handler for handler in group.get("hooks", []) if not _is_managed_codex_handler(handler)]
            if remaining:
                group["hooks"] = remaining
                kept_groups.append(group)
        hooks[event] = kept_groups
    for event, groups in bundled.items():
        existing = hooks.setdefault(event, [])
        for original in groups:
            group = json.loads(json.dumps(original))
            for handler in group["hooks"]:
                handler["command"] = command
            existing.append(group)
    plan.append(("file", hook_file, json.dumps(config, indent=2) + "\n"))
    return plan


def plan_cli(home):
    destination = home / ".local/bin/rex-annotation"
    if destination.is_symlink() and destination.resolve() == (ROOT / "bin/rex-annotation").resolve():
        return []
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"Refusing to replace unrelated CLI entry {destination}; move it yourself first")
    existing = shutil.which("rex-annotation")
    if existing:
        print(f"rex-annotation is already available at {existing}; leaving it unchanged")
        return []
    return [("link", destination, ROOT / "bin/rex-annotation")]


def _apply(plan):
    for kind, path, value in plan:
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "link":
            path.symlink_to(value, target_is_directory=value.is_dir())
        elif not path.exists() or path.read_text() != value:
            path.write_text(value)
        print(f"Installed {path}")


def _install_pi(timeout=20):
    executable = shutil.which("pi")
    if not executable:
        raise ValueError("Pi CLI 'pi' is not available on PATH")
    try:
        result = subprocess.run([executable, "install", str(ROOT)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        parts = [part.decode(errors="replace") if isinstance(part, bytes) else (part or "") for part in (error.stdout, error.stderr)]
        raise ValueError(f"pi install timed out after {timeout}s; inspect Pi settings before retrying\n{''.join(parts)}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode:
        raise ValueError(f"pi install failed with exit code {result.returncode}")


def _reload_rex():
    executable = shutil.which("rex")
    if not executable:
        raise ValueError("Rex CLI is missing; install Rex before requesting --reload-rex")
    for command in ("check", "reload"):
        try:
            result = subprocess.run([executable, "config", command], capture_output=True, text=True, timeout=8)
        except subprocess.TimeoutExpired:
            raise ValueError("Rex config " + command + " timed out; config files were saved. Inspect rex-annotation status before retrying")
        if result.returncode:
            raise ValueError("Rex config " + command + " failed; config files were saved. " + result.stdout + result.stderr)
        if result.stdout:
            print(result.stdout.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rex", action="store_true", help="install the Rex loader (default)")
    parser.add_argument("--pi", action="store_true", help="register this root package with Pi")
    parser.add_argument("--codex", action="store_true", help="link the Codex skill and merge its native hooks")
    parser.add_argument("--claude", action="store_true", help="merge automatic lifecycle hooks into Claude settings")
    parser.add_argument("--all", action="store_true", help="opt in to Pi, Codex, and Claude along with Rex")
    parser.add_argument("--detect", action="store_true", help="configure integrations only for agent CLIs already on PATH")
    parser.add_argument("--reload-rex", action="store_true", help="check and reload Rex config after setup; never reload an agent")
    args = parser.parse_args(argv)
    home = Path.home()
    selected = {name for name in ("pi", "codex", "claude") if getattr(args, name)}
    if args.all:
        selected.update(("pi", "codex", "claude"))
    if args.detect:
        detected = {name for name in ("pi", "codex", "claude") if shutil.which(name)}
        selected.update(detected)
        print("Detected agents: " + (", ".join(sorted(detected)) or "none (Rex-only setup)"))
    try:
        plan = plan_rex(home)
        if "codex" in selected:
            plan += plan_codex(home)
        if "claude" in selected:
            plan += plan_claude(home)
        plan += plan_cli(home)
        # Validate and prepare the local changes before invoking a selected agent CLI.
        if "pi" in selected:
            _install_pi()
        _apply(plan)
        if args.reload_rex:
            _reload_rex()
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print("Rex config reloaded. No agent process was reloaded." if args.reload_rex else "No runtime reloaded. Use --reload-rex to validate and activate Rex config; agents stay untouched.")
    print("Next: rex-annotation status (read-only checks with specific fixes)")
    if "codex" in selected:
        print("Review and trust the local Codex hooks yourself in /hooks; trust is never bypassed by this installer.")
    if "pi" in selected:
        print("Pi registration requested for this checkout; an already-running Pi process is unchanged.")
    if "claude" in selected:
        config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or str(home / ".claude")).expanduser()
        print(f"Claude lifecycle hooks merged into {config_dir / 'settings.json'}; trust and hook-disable policies were not changed.")
    print("Use normal codex/claude commands from a Rex pane; review each CLI's own trust prompts and activation state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
