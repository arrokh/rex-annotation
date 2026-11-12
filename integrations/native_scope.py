#!/usr/bin/env python3
"""Resolve exact Rex foreground scope for native Codex and Claude hooks."""

import ctypes
import errno
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import sys
import time
from collections import namedtuple
from typing import Any, Dict, Optional

from session_replies import ReplyError, _require_token

MAX_REX_OUTPUT = 64 * 1024
MAX_OPEN_FILES_OUTPUT = 128 * 1024
REX_TIMEOUT_SECONDS = 1.6
OPEN_FILES_TIMEOUT_SECONDS = 1.5
MAX_ANCESTRY_DEPTH = 64
CODEX_ROLLOUT = re.compile(
    r"^rollout-(\d{4})-(\d{2})-(\d{2})T\d{2}-\d{2}-\d{2}-"
    r"([0-9a-fA-F-]{36})(?:_([0-9a-fA-F-]{36}))?\.jsonl$"
)

ProcessInfo = namedtuple("ProcessInfo", "pid parent_pid uid start_identity path", defaults=[""])
NativeScope = namedtuple("NativeScope", "rex_session rex_block pid native_child_pid", defaults=[None])


def _linux_process_info(pid: int) -> ProcessInfo:
    stat_path = "/proc/{}/stat".format(pid)
    try:
        with open(stat_path, "r", encoding="ascii") as process_stat:
            data = process_stat.read(8192)
        close = data.rfind(")")
        if close < 0:
            raise ReplyError("cannot identify process ancestry")
        fields = data[close + 2 :].split()
        if len(fields) <= 19 or fields[0] == "Z":
            raise ReplyError("process is no longer running")
        parent_pid = int(fields[1])
        start_time = fields[19]
        owner = os.stat("/proc/{}".format(pid)).st_uid
        with open(stat_path, "r", encoding="ascii") as process_stat:
            check = process_stat.read(8192)
        check_close = check.rfind(")")
        check_fields = check[check_close + 2 :].split() if check_close >= 0 else []
        if len(check_fields) <= 19 or check_fields[19] != start_time:
            raise ReplyError("process identity changed during ancestry check")
    except FileNotFoundError:
        raise ReplyError("process is no longer running")
    except (OSError, ValueError, IndexError) as error:
        if isinstance(error, ReplyError):
            raise
        raise ReplyError("cannot identify process ancestry: {}".format(error))
    if owner != os.geteuid() or parent_pid < 0:
        raise ReplyError("process owner or ancestry is not trusted")
    return ProcessInfo(pid, parent_pid, owner, "linux:{}".format(start_time), os.readlink("/proc/{}/exe".format(pid)))


def _darwin_process_info(pid: int) -> ProcessInfo:
    # PROC_PIDTBSDINFO is the public libproc interface; never run setuid /bin/ps.
    class ProcBsdInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in (
            "flags", "status", "xstatus", "pid", "ppid", "uid", "gid",
            "ruid", "rgid", "svuid", "svgid", "reserved")]
        _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
        _fields_ += [(name, ctypes.c_uint32) for name in (
            "nfiles", "pgid", "pjobc", "tdev", "tpgid")]
        _fields_ += [("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64),
                     ("start_usec", ctypes.c_uint64)]

    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        query = library.proc_pidinfo
        query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        query.restype = ctypes.c_int
        info = ProcBsdInfo()
        size = query(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        error = ctypes.get_errno()
    except (OSError, AttributeError) as error:
        raise ReplyError("cannot identify process ancestry: {}".format(error))
    if size == 0 and error in (errno.ESRCH, errno.ENOENT):
        raise ReplyError("process is no longer running")
    if size != ctypes.sizeof(info):
        raise ReplyError("cannot identify process ancestry via libproc")
    if info.status == 5 or info.pid != pid or info.uid != os.geteuid() or not info.start_sec:
        raise ReplyError("process owner or identity is not trusted")
    if info.ppid < 0:
        raise ReplyError("cannot identify process ancestry")
    path_buffer = ctypes.create_string_buffer(4096)
    path_query = library.proc_pidpath
    path_query.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    path_query.restype = ctypes.c_int
    if path_query(pid, path_buffer, len(path_buffer)) <= 0:
        raise ReplyError("cannot identify the process executable")
    return ProcessInfo(pid, info.ppid, info.uid,
                       "darwin:{}:{}".format(info.start_sec, info.start_usec),
                       os.fsdecode(path_buffer.value))


def _process_info(pid: int) -> ProcessInfo:
    if pid <= 0:
        raise ReplyError("PID must be a positive integer")
    if sys.platform.startswith("linux"):
        return _linux_process_info(pid)
    if sys.platform == "darwin":
        return _darwin_process_info(pid)
    raise ReplyError("process ancestry is unsupported on this platform")


def _open_codex_rollouts(pid: int):
    """Return only canonical rollout files open by this exact Codex process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ReplyError("Codex PID must be a positive integer")
    process = _process_info(pid)
    if _agent_path(process.path) != "codex":
        raise ReplyError("foreground process is not Codex")
    start_identity = process.start_identity
    names = []

    if sys.platform.startswith("linux"):
        directory = "/proc/{}/fd".format(pid)
        try:
            descriptors = os.listdir(directory)
        except OSError as error:
            raise ReplyError("cannot inspect foreground Codex files: {}".format(error))
        if len(descriptors) > 8192:
            raise ReplyError("foreground Codex has too many open files to inspect safely")
        for descriptor in descriptors:
            try:
                names.append(os.readlink(os.path.join(directory, descriptor)))
            except FileNotFoundError:
                continue  # The descriptor closed during enumeration.
            except OSError as error:
                raise ReplyError("cannot inspect foreground Codex files: {}".format(error))
    elif sys.platform == "darwin":
        lsof = "/usr/sbin/lsof"
        try:
            executable = os.lstat(lsof)
        except OSError as error:
            raise ReplyError("macOS lsof is unavailable: {}".format(error))
        if (not stat.S_ISREG(executable.st_mode) or executable.st_uid != 0
                or executable.st_mode & (stat.S_ISUID | stat.S_ISGID | 0o022)):
            raise ReplyError("refusing an untrusted or set-ID lsof executable")
        try:
            process = subprocess.Popen([lsof, "-n", "-p", str(pid), "-Fn"], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True)
        except OSError as error:
            raise ReplyError("cannot inspect foreground Codex files: {}".format(error))
        output = bytearray()
        selector = selectors.DefaultSelector()
        try:
            if process.stdout is None:
                raise ReplyError("lsof did not provide an output stream")
            selector.register(process.stdout, selectors.EVENT_READ)
            eof = False
            deadline = time.monotonic() + OPEN_FILES_TIMEOUT_SECONDS
            while not eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ReplyError("foreground Codex file inspection timed out")
                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    eof = True
                    break
                output.extend(chunk)
                if len(output) > MAX_OPEN_FILES_OUTPUT:
                    raise ReplyError("foreground Codex file list is oversized")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReplyError("foreground Codex file inspection timed out")
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise ReplyError("foreground Codex file inspection timed out")
        finally:
            selector.close()
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            if process.stdout is not None:
                process.stdout.close()
        if code != 0:
            raise ReplyError("cannot inspect foreground Codex files (lsof exit {})".format(code))
        try:
            names.extend(line[1:] for line in os.fsdecode(bytes(output)).splitlines() if line.startswith("n"))
        except UnicodeError as error:
            raise ReplyError("foreground Codex file paths are malformed: {}".format(error))
    else:
        raise ReplyError("open Codex transcript inspection is unsupported on this platform")

    matches = set()
    for name in names:
        if name.endswith(" (deleted)") or not os.path.isabs(name):
            continue
        normalized = os.path.realpath(name)
        parts = normalized.split(os.sep)
        match = CODEX_ROLLOUT.fullmatch(os.path.basename(normalized))
        if not match or len(parts) < 5 or parts[-5] != "sessions":
            continue
        year, month, day = match.group(1, 2, 3)
        if tuple(parts[-4:-1]) != (year, month, day):
            continue
        try:
            import uuid
            uuid.UUID(match.group(4))
            info = os.stat(normalized)
        except (OSError, ValueError):
            continue
        if stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid():
            matches.add(normalized)

    current = _process_info(pid)
    if current.start_identity != start_identity or _agent_path(current.path) != "codex":
        raise ReplyError("foreground Codex process changed during file inspection")
    return sorted(matches)


def _is_ancestor(ancestor_pid: int, ancestor_start: str, hook_pid: int, agent: str) -> bool:
    """Require the foreground agent to be the nearest matching native ancestor."""
    if ancestor_pid <= 0 or hook_pid <= 0 or ancestor_pid == hook_pid:
        return False
    current_pid = hook_pid
    visited = set()
    for _ in range(MAX_ANCESTRY_DEPTH):
        if current_pid in visited or current_pid <= 1:
            return False
        visited.add(current_pid)
        try:
            current = _process_info(current_pid)
        except (ReplyError, OSError):
            return False
        if current_pid == ancestor_pid:
            return current.start_identity == ancestor_start
        # A nested/background CLI must not replace its parent's conversation.
        if current_pid != hook_pid and _agent_path(current.path) == agent:
            return False
        current_pid = current.parent_pid
    return False

def _run_rex_process(session: str, block: str) -> Dict[str, Any]:
    executable = shutil.which("rex")
    if not executable:
        raise ReplyError("cannot locate the Rex executable")
    command = [executable, "--autostart=false", "--timeout", "1s", "block", "call",
               "-s", session, "-b", block, "process"]
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as error:
        raise ReplyError("cannot query the Rex foreground process: {}".format(error))

    output = bytearray()
    deadline = time.monotonic() + REX_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    try:
        if process.stdout is None:
            raise ReplyError("Rex process query has no output stream")
        selector.register(process.stdout, selectors.EVENT_READ)
        eof = False
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReplyError("Rex foreground process query timed out")
            events = selector.select(remaining)
            if not events:
                raise ReplyError("Rex foreground process query timed out")
            for key, _ in events:
                chunk = os.read(key.fd, min(8192, MAX_REX_OUTPUT + 1 - len(output)))
                if not chunk:
                    selector.unregister(key.fileobj)
                    eof = True
                    break
                output.extend(chunk)
                if len(output) > MAX_REX_OUTPUT:
                    raise ReplyError("Rex foreground process result is oversized")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReplyError("Rex foreground process query timed out")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise ReplyError("Rex foreground process query timed out")
    except ReplyError:
        raise
    except (OSError, ValueError) as error:
        raise ReplyError("cannot read the Rex foreground process result: {}".format(error))
    finally:
        selector.close()
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        if process.stdout is not None:
            process.stdout.close()

    if returncode != 0:
        raise ReplyError("Rex foreground process query failed (exit {})".format(returncode))
    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReplyError("Rex foreground process result is malformed: {}".format(error))
    if not isinstance(result, dict):
        raise ReplyError("Rex foreground process result must be a JSON object")
    return result


def _recognized_agent(process: Dict[str, Any]) -> Optional[str]:
    last_exit = process.get("last_exit")
    if last_exit is not None and last_exit is not False:
        return None
    foreground = process.get("foreground")
    if not isinstance(foreground, dict):
        return None
    path = foreground.get("path")
    if not isinstance(path, str):
        return None
    base = path.rsplit("/", 1)[-1]
    if base == "codex":
        return "codex"
    if base in ("claude", "cux") or re.search(r"/claude/versions/[0-9.]+$", path):
        return "claude"
    return None


def _foreground_pid(process: Dict[str, Any]) -> Optional[int]:
    foreground = process.get("foreground")
    if not isinstance(foreground, dict):
        return None
    pid = foreground.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    return pid


def _positive_pid(value: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ReplyError("REX_PID must be a positive integer")
    pid = int(value)
    if pid > 2 ** 31 - 1:
        raise ReplyError("REX_PID must be a positive integer")
    return pid


def resolve_scope(agent: str, environ: Optional[Dict[str, str]] = None,
                  hook_pid: Optional[int] = None):
    """Resolve the foreground owner and any CUX-managed native Claude child."""
    if agent not in ("codex", "claude"):
        raise ReplyError("unsupported native agent")
    env = os.environ if environ is None else environ
    if not env.get("REX_SESSION") or not env.get("REX_BLOCK"):
        return None
    session = _require_token(env["REX_SESSION"], "Rex session id")
    block = _require_token(env["REX_BLOCK"], "Rex block id")
    caller = os.getpid() if hook_pid is None else hook_pid
    explicit = env.get("REX_PID")
    if explicit:
        # Retain the existing explicit-launcher/manual binding contract.
        pid = _positive_pid(explicit)
    else:
        process = _run_rex_process(session, block)
        if _recognized_agent(process) != agent:
            return None
        pid = _foreground_pid(process)
        if pid is None:
            return None
    try:
        info = _process_info(pid)
    except (ReplyError, OSError):
        return None
    if agent == "claude" and info.path.rsplit("/", 1)[-1] == "cux":
        child = _cux_native_child(pid, info.start_identity, caller)
        return NativeScope(session, block, pid, child) if child is not None else None
    if not explicit and _agent_path(info.path) != agent:
        return None
    if not _is_ancestor(pid, info.start_identity, caller, agent):
        return None
    return NativeScope(session, block, pid)


def rex_scope(agent: str, environ=None, hook_pid=None):
    """Compatibility tuple for helpers that do not need a native child binding."""
    scope = resolve_scope(agent, environ, hook_pid)
    return tuple(scope[:3]) if scope is not None else None


def _cux_native_child(wrapper_pid: int, wrapper_start: str, caller: int):
    child, visited = None, set()
    current = caller
    for _ in range(MAX_ANCESTRY_DEPTH):
        if current <= 1 or current in visited:
            return None
        visited.add(current)
        try:
            info = _process_info(current)
        except (ReplyError, OSError):
            return None
        if current == wrapper_pid:
            return child if info.start_identity == wrapper_start else None
        if current != caller:
            if _agent_path(info.path) == "claude":
                if child is not None:
                    return None  # A nested Claude cannot replace the managed child.
                child = current
            elif info.path.rsplit("/", 1)[-1] == "cux":
                return None
        current = info.parent_pid
    return None


def _agent_path(path: str) -> Optional[str]:
    if path.rsplit("/", 1)[-1] == "codex":
        return "codex"
    if path.rsplit("/", 1)[-1] == "claude" or re.search(r"/claude/versions/[0-9.]+$", path):
        return "claude"
    return None
