#!/usr/bin/env python3
"""Exact-session reply bindings and native transcript readers for Rex Annotation."""

import argparse
import datetime as _datetime
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_TRANSCRIPT_BYTES = 4 * 1024 * 1024
MAX_TRANSCRIPT_ENTRIES = 5000
BINDING_VERSION = 1
ANSI_ESCAPE = re.compile(
    r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[PX^_].*?\x1b\\|[@-_])"
)


class ReplyError(Exception):
    """A stale, mismatched, unsafe, or unsupported session binding."""


def _require_token(value: Any, label: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ReplyError("missing or invalid " + label)
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ReplyError(label + " contains control characters")
    if not value.strip():
        raise ReplyError("missing or invalid " + label)
    return value


def _process_start_identity(pid: int) -> str:
    if pid <= 0:
        raise ReplyError("PID must be a positive integer")

    if sys.platform.startswith("linux"):
        try:
            with open("/proc/{}/stat".format(pid), "r", encoding="ascii") as process_stat:
                data = process_stat.read(8192)
            close = data.rfind(")")
            if close < 0:
                raise ReplyError("cannot identify foreground process start")
            fields = data[close + 2 :].split()
            if len(fields) <= 19 or fields[0] == "Z":
                raise ReplyError("foreground process is no longer running")
            return "linux:{}".format(fields[19])
        except FileNotFoundError:
            raise ReplyError("foreground process is no longer running")
        except OSError as error:
            raise ReplyError("cannot identify foreground process: {}".format(error))

    if sys.platform == "darwin":
        # Public libproc API: sys/proc_info.h PROC_PIDTBSDINFO / proc_bsdinfo.
        # Avoid executing setuid /bin/ps, which macOS forbids inside a sandbox.
        import ctypes
        import errno

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
            raise ReplyError("cannot identify foreground process: {}".format(error))
        if size == 0 and error in (errno.ESRCH, errno.ENOENT):
            raise ReplyError("foreground process is no longer running")
        if size != ctypes.sizeof(info):
            raise ReplyError("cannot identify foreground process via libproc: " + (os.strerror(error) if error else "unexpected result size"))
        if info.status == 5:  # SZOMB
            raise ReplyError("foreground process is no longer running")
        if info.pid != pid or info.uid != os.geteuid() or not info.start_sec:
            raise ReplyError("foreground process identity or owner changed")
        return "darwin:{}:{}".format(info.start_sec, info.start_usec)

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                raise ReplyError("foreground process is no longer running")
            try:
                created = FILETIME()
                exited = FILETIME()
                kernel_time = FILETIME()
                user_time = FILETIME()
                if not kernel.GetProcessTimes(
                    handle,
                    ctypes.byref(created),
                    ctypes.byref(exited),
                    ctypes.byref(kernel_time),
                    ctypes.byref(user_time),
                ):
                    raise ReplyError("cannot identify foreground process start")
                code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                    raise ReplyError("foreground process is no longer running")
                start = (created.high << 32) | created.low
                return "windows:{}".format(start)
            finally:
                kernel.CloseHandle(handle)
        except ReplyError:
            raise
        except Exception as error:
            raise ReplyError("cannot identify foreground process: {}".format(error))

    raise ReplyError("process start identity is unsupported on this platform")


def _state_directory() -> Path:
    override = os.environ.get("REX_ANNOTATION_STATE_DIR")
    if override:
        state_home = Path(override).expanduser()
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME")
        state_home = Path(xdg_state).expanduser() if xdg_state else Path.home() / ".local" / "state"
    if not state_home.is_absolute():
        raise ReplyError("state directory must be an absolute path")
    try:
        state_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        if state_home.is_symlink() or not state_home.is_dir():
            raise ReplyError("state directory must be a real directory")
        directory = state_home / "rex-annotation" / "reply-bindings"
        for path in (directory.parent, directory):
            try:
                path.mkdir(mode=0o700)
            except FileExistsError:
                pass
            if path.is_symlink() or not path.is_dir():
                raise ReplyError("reply binding directory must not be a symlink")
            info = path.stat()
            if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
                raise ReplyError("reply binding directory is not owned by this user")
            os.chmod(str(path), 0o700)
        return directory
    except ReplyError:
        raise
    except OSError as error:
        raise ReplyError("cannot create private reply binding directory: {}".format(error))


def _binding_path(directory: Path, pid: int, start_identity: str) -> Path:
    key = hashlib.sha256((str(pid) + ":" + start_identity).encode("utf-8")).hexdigest()
    return directory / (str(pid) + "-" + key[:32] + ".json")


def _atomic_write(path: Path, record: Dict[str, Any]) -> None:
    directory = path.parent
    fd, temporary_name = tempfile.mkstemp(prefix=".binding-", dir=str(directory))
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temporary), str(path))
        try:
            directory_fd = os.open(str(directory), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_binding(path: Path) -> Dict[str, Any]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise ReplyError("reply binding is not a regular file")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise ReplyError("reply binding is not owned by this user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ReplyError("reply binding permissions are not private")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(path), flags)
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ReplyError("reply binding metadata is oversized")
        record = json.loads(raw.decode("utf-8"))
        if not isinstance(record, dict) or record.get("version") != BINDING_VERSION:
            raise ReplyError("reply binding metadata is malformed or unsupported")
        return record
    except ReplyError:
        raise
    except FileNotFoundError:
        raise ReplyError("no active reply binding for this PID")
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReplyError("cannot read reply binding: {}".format(error))


def _open_transcript(path_text: str) -> bytes:
    path = Path(path_text)
    if not path.is_absolute() or path.suffix != ".jsonl":
        raise ReplyError("registered transcript path must be an absolute .jsonl file")
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise ReplyError("registered transcript is not a regular file")
        if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
            raise ReplyError("registered transcript is not owned by this user")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(path), flags)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_TRANSCRIPT_BYTES + 1)
            final_size = os.fstat(stream.fileno()).st_size
        if len(data) > MAX_TRANSCRIPT_BYTES or final_size > MAX_TRANSCRIPT_BYTES:
            raise ReplyError("registered transcript exceeds the 4 MiB limit")
        return data
    except ReplyError:
        raise
    except FileNotFoundError:
        raise ReplyError("registered transcript is stale or missing")
    except OSError as error:
        raise ReplyError("cannot read registered transcript: {}".format(error))


def _jsonl_entries(data: bytes) -> List[Dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReplyError("transcript is not valid UTF-8: {}".format(error))
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()
    if len(raw_lines) > MAX_TRANSCRIPT_ENTRIES:
        raise ReplyError("transcript exceeds the 5000-entry limit")
    entries = []
    for number, raw_line in enumerate(raw_lines, 1):
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if not line:
            raise ReplyError("transcript has an empty entry at line {}".format(number))
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ReplyError("malformed transcript entry at line {}: {}".format(number, error))
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            raise ReplyError("malformed transcript entry at line {}".format(number))
        entries.append(entry)
    return entries


def _clean_visible_text(text: str) -> str:
    text = ANSI_ESCAPE.sub("", text)
    for char in text:
        if char not in "\n\t" and unicodedata.category(char) == "Cc":
            raise ReplyError("visible assistant text contains control characters")
    return text


def _timestamp_key(timestamp: Any) -> _datetime.datetime:
    if not isinstance(timestamp, str) or not timestamp:
        raise ReplyError("assistant transcript entry has no timestamp")
    _require_token(timestamp, "assistant timestamp", 128)
    try:
        parsed = _datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReplyError("assistant timestamp is malformed: {}".format(error))
    if parsed.tzinfo is None:
        raise ReplyError("assistant timestamp must include a timezone")
    return parsed.astimezone(_datetime.timezone.utc)


def _make_reply(reply_id: str, timestamp: Any, text: str, order: int) -> Tuple[_datetime.datetime, int, Dict[str, str]]:
    reply_id = _require_token(reply_id, "assistant reply id", 512)
    timestamp_text = _require_token(timestamp, "assistant timestamp", 128)
    key = _timestamp_key(timestamp_text)
    visible = _clean_visible_text(text)
    if not visible.strip():
        raise ReplyError("assistant transcript entry contains no visible text")
    return key, order, {"id": reply_id, "timestamp": timestamp_text, "text": visible}


def _claude_session_matches(entries: List[Dict[str, Any]], path: Path, conversation_id: str) -> None:
    seen = set()
    for entry in entries:
        for key in ("sessionId", "session_id"):
            value = entry.get(key)
            if value is not None:
                seen.add(_require_token(value, "Claude transcript session id", 512))
    if seen and seen != {conversation_id}:
        raise ReplyError("Claude transcript session id does not match the active binding")
    if not seen and path.stem != conversation_id:
        raise ReplyError("Claude transcript does not identify the bound session")
    if not entries and path.stem != conversation_id:
        raise ReplyError("empty Claude transcript path does not identify the bound session")


def _claude_replies(path: Path, conversation_id: str, data: bytes) -> List[Dict[str, str]]:
    entries = _jsonl_entries(data)
    _claude_session_matches(entries, path, conversation_id)

    # Claude records parent/child message ids. A transcript with multiple children
    # for one parent does not identify which branch is active, so fail closed.
    children: Dict[str, set] = {}
    seen_message_ids = set()
    known_ids = {
        entry["uuid"]
        for entry in entries
        if isinstance(entry.get("uuid"), str) and entry.get("type") != "progress"
    }
    roots = set()
    for entry in entries:
        if entry.get("type") not in ("assistant", "user", "summary") or entry.get("isSidechain"):
            continue
        message_id = entry.get("uuid")
        if not isinstance(message_id, str):
            raise ReplyError("Claude conversation entry has no message id")
        message_id = _require_token(message_id, "Claude message id", 512)
        if message_id in seen_message_ids:
            raise ReplyError("Claude transcript repeats a message id")
        seen_message_ids.add(message_id)
        if "parentUuid" not in entry:
            raise ReplyError("Claude transcript has no parent link; refusing to guess its branch")
        parent_id = entry.get("parentUuid")
        if parent_id is None:
            if entry.get("type") in ("assistant", "user"):
                roots.add(message_id)
        else:
            parent_id = _require_token(parent_id, "Claude parent message id", 512)
            if parent_id not in known_ids:
                raise ReplyError("Claude transcript has an unresolved parent link")
            children.setdefault(parent_id, set()).add(message_id)
            if len(children[parent_id]) > 1:
                raise ReplyError("Claude transcript has an ambiguous active branch")
    if len(roots) > 1:
        raise ReplyError("Claude transcript has an ambiguous active branch")

    replies_with_order = []
    used_ids = set()
    for order, entry in enumerate(entries):
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            raise ReplyError("Claude assistant transcript entry is malformed")
        if message.get("role") != "assistant" or entry.get("isMeta") or message.get("isMeta"):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        text_parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                value = block.get("text")
                if not isinstance(value, str):
                    raise ReplyError("Claude text block is malformed")
                text_parts.append(value)
        if not text_parts:
            continue
        text = _clean_visible_text("".join(text_parts))
        if not text.strip():
            continue
        reply_id = entry.get("uuid") or message.get("id")
        if not isinstance(reply_id, str) or not reply_id:
            reply_id = hashlib.sha256(
                json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        if reply_id in used_ids:
            raise ReplyError("Claude transcript has duplicate assistant reply ids")
        used_ids.add(reply_id)
        timestamp = entry.get("timestamp")
        replies_with_order.append(_make_reply(reply_id, timestamp, text, order))

    replies_with_order.sort(key=lambda item: (item[0], item[1]))
    return [reply for _, _, reply in replies_with_order]


def _codex_session_matches(entries: List[Dict[str, Any]], conversation_id: str) -> None:
    session_ids = []
    for entry in entries:
        if entry.get("type") != "session_meta":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            raise ReplyError("Codex session metadata is malformed")
        session_id = payload.get("id")
        if session_id is None:
            raise ReplyError("Codex session metadata has no session id")
        session_ids.append(_require_token(session_id, "Codex transcript session id", 512))
    if not session_ids or any(session_id != conversation_id for session_id in session_ids):
        raise ReplyError("Codex transcript session id does not match the active binding")


def _codex_replies(path: Path, conversation_id: str, data: bytes) -> List[Dict[str, str]]:
    entries = _jsonl_entries(data)
    _codex_session_matches(entries, conversation_id)
    if any(entry.get("type") == "event_msg" and isinstance(entry.get("payload"), dict)
           and entry["payload"].get("type") == "thread_rolled_back" for entry in entries):
        raise ReplyError("Codex transcript contains a rollback; active history reconstruction is unsupported, refusing undone replies")
    replies_with_order = []
    used_ids = set()
    for order, entry in enumerate(entries):
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            raise ReplyError("Codex response item is malformed")
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            continue
        channel = payload.get("channel", entry.get("channel"))
        if channel is not None and channel not in ("final", "commentary"):
            continue
        phase = payload.get("phase", entry.get("phase"))
        if phase is not None and phase not in ("final_answer", "partial_answer", "commentary", "final"):
            continue
        content = payload.get("content")
        if not isinstance(content, list):
            raise ReplyError("Codex assistant message content is malformed")
        text_parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "output_text":
                value = block.get("text")
            elif block_type == "refusal":
                value = block.get("refusal")
            else:
                continue
            if not isinstance(value, str):
                raise ReplyError("Codex visible text block is malformed")
            text_parts.append(value)
        if not text_parts:
            continue
        text = _clean_visible_text("".join(text_parts))
        if not text.strip():
            continue
        timestamp = entry.get("timestamp")
        reply_id = payload.get("id") or entry.get("id")
        if not isinstance(reply_id, str) or not reply_id:
            reply_id = hashlib.sha256(
                json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        if reply_id in used_ids:
            raise ReplyError("Codex transcript has duplicate assistant reply ids")
        used_ids.add(reply_id)
        replies_with_order.append(_make_reply(reply_id, timestamp, text, order))
    replies_with_order.sort(key=lambda item: (item[0], item[1]))
    return [reply for _, _, reply in replies_with_order]


def _parse_transcript(agent: str, transcript_path: str, conversation_id: str) -> List[Dict[str, str]]:
    path = Path(transcript_path)
    data = _open_transcript(transcript_path)
    if agent == "claude":
        return _claude_replies(path, conversation_id, data)
    if agent == "codex":
        return _codex_replies(path, conversation_id, data)
    raise ReplyError("unsupported agent: " + agent)


def register_binding(
    agent: str,
    pid: int,
    rex_session: str,
    rex_block: str,
    conversation_id: str,
    transcript_path: str,
    allow_pending: bool = False,
    native_child_pid: Optional[int] = None,
) -> Dict[str, Any]:
    if agent not in ("codex", "claude"):
        raise ReplyError("agent must be codex or claude")
    rex_session = _require_token(rex_session, "Rex session id")
    rex_block = _require_token(rex_block, "Rex block id")
    conversation_id = _require_token(conversation_id, "conversation id")
    transcript_path = _require_token(transcript_path, "transcript path", 4096)
    source = Path(transcript_path).expanduser()
    if not source.is_absolute():
        raise ReplyError("transcript path must be absolute")
    pending = False
    try:
        source = source.resolve(strict=True)
        info = source.stat()
    except FileNotFoundError as error:
        if not allow_pending or source.suffix != ".jsonl":
            raise ReplyError("transcript path is unavailable: {}".format(error))
        source, info, pending = source.resolve(strict=False), None, True
    except OSError as error:
        raise ReplyError("transcript path is unavailable: {}".format(error))
    if source.suffix != ".jsonl" or (info is not None and not stat.S_ISREG(info.st_mode)):
        raise ReplyError("transcript path must identify a regular .jsonl file")
    if info is not None and hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise ReplyError("transcript is not owned by this user")

    start_identity = _process_start_identity(pid)
    child_start_identity = None
    if native_child_pid is not None:
        if isinstance(native_child_pid, bool) or not isinstance(native_child_pid, int) or native_child_pid <= 0:
            raise ReplyError("native child PID must be a positive integer")
        child_start_identity = _process_start_identity(native_child_pid)
    directory = _state_directory()
    path = _binding_path(directory, pid, start_identity)
    record = {
        "version": BINDING_VERSION,
        "agent": agent,
        "pid": pid,
        "process_start": start_identity,
        "rex_session": rex_session,
        "rex_block": rex_block,
        "conversation_id": conversation_id,
        "transcript_path": str(source),
        "pending": pending,
        "registered_at": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
    }
    if native_child_pid is not None:
        record["native_child_pid"] = native_child_pid
        record["native_child_start"] = child_start_identity
    _atomic_write(path, record)
    return record


def _validate_native_child(record: Dict[str, Any]) -> None:
    if "native_child_pid" not in record and "native_child_start" not in record:
        return
    child_pid = record.get("native_child_pid")
    child_start = record.get("native_child_start")
    if isinstance(child_pid, bool) or not isinstance(child_pid, int) or child_pid <= 0 or not isinstance(child_start, str) or not child_start:
        raise ReplyError("native child binding metadata is malformed")
    try:
        current_child_start = _process_start_identity(child_pid)
    except ReplyError as error:
        raise ReplyError("native child process changed or exited: {}".format(error))
    if current_child_start != child_start:
        raise ReplyError("native child process changed or exited")


def _current_binding(pid: int, agent: str, rex_session: str, rex_block: str) -> Tuple[Path, Dict[str, Any]]:
    start_identity = _process_start_identity(pid)
    path = _binding_path(_state_directory(), pid, start_identity)
    record = _read_binding(path)
    expected = {
        "agent": agent,
        "pid": pid,
        "process_start": start_identity,
        "rex_session": rex_session,
        "rex_block": rex_block,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise ReplyError("active reply binding does not match {}".format(key))
    _validate_native_child(record)
    _require_token(record.get("conversation_id"), "bound conversation id")
    _require_token(record.get("transcript_path"), "bound transcript path", 4096)
    return path, record


def _ensure_binding_unchanged(path: Path, pid: int, record: Dict[str, Any]) -> None:
    _validate_native_child(record)
    start_identity = _process_start_identity(pid)
    if start_identity != record.get("process_start"):
        raise ReplyError("foreground process changed during validation")
    current_path = _binding_path(_state_directory(), pid, start_identity)
    if current_path != path or _read_binding(current_path) != record:
        raise ReplyError("active session changed during validation")


def _verified_binding(
    agent: str,
    pid: int,
    rex_session: str,
    rex_block: str,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    path, record = _current_binding(pid, agent, rex_session, rex_block)
    if conversation_id is not None and record.get("conversation_id") != conversation_id:
        raise ReplyError("bound conversation id changed")
    # Reading and validating the exact source is part of validation: an old binding
    # cannot survive transcript replacement, truncation, or a different native session.
    _parse_transcript(agent, record["transcript_path"], record["conversation_id"])
    _ensure_binding_unchanged(path, pid, record)
    return record


def unregister_binding(
    agent: str,
    pid: int,
    rex_session: str,
    rex_block: str,
    conversation_id: str,
    native_child_pid: Optional[int] = None,
) -> bool:
    start_identity = _process_start_identity(pid)
    path = _binding_path(_state_directory(), pid, start_identity)
    try:
        record = _read_binding(path)
    except ReplyError as error:
        if str(error).startswith("no active reply binding"):
            return False
        raise
    expected = (agent, pid, start_identity, rex_session, rex_block, conversation_id)
    actual = (
        record.get("agent"),
        record.get("pid"),
        record.get("process_start"),
        record.get("rex_session"),
        record.get("rex_block"),
        record.get("conversation_id"),
    )
    if actual != expected:
        return False
    if native_child_pid is not None:
        try:
            _validate_native_child(record)
        except ReplyError:
            return False
        if record.get("native_child_pid") != native_child_pid:
            return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def invalidate_binding(agent: str, pid: int, rex_session: str, rex_block: str) -> bool:
    """A native SessionStart must retire old state even if the new path is absent."""
    try:
        _, record = _current_binding(pid, agent, rex_session, rex_block)
    except ReplyError as error:
        # A dead CUX child is already unusable; the next registration replaces
        # its owned record. Never require the exited child to validate a resume.
        if str(error).startswith(("no active reply binding", "native child process changed or exited")):
            return False
        raise
    return unregister_binding(agent, pid, rex_session, rex_block, record["conversation_id"])


def _codex_thread_id_matches(name: str, thread_id: str) -> bool:
    # Current Codex rollouts are date-partitioned JSONL files whose canonical
    # basename carries the thread id; reverted rollouts append a second UUID.
    pattern = re.compile(
        r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-"
        r"([0-9a-fA-F-]{36})(?:_([0-9a-fA-F-]{36}))?\.jsonl$"
    )
    match = pattern.fullmatch(name)
    return bool(match and match.group(1).lower() == thread_id.lower())


def find_codex_transcript(thread_id: str, codex_home: Optional[str] = None) -> str:
    thread_id = _require_token(thread_id, "CODEX_THREAD_ID", 128)
    try:
        import uuid

        thread_id = str(uuid.UUID(thread_id))
    except (ValueError, AttributeError):
        raise ReplyError("CODEX_THREAD_ID must be a Codex UUID")
    home = Path(codex_home).expanduser() if codex_home else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    sessions = home / "sessions"
    if not sessions.is_dir() or sessions.is_symlink():
        raise ReplyError("Codex sessions directory is unavailable; enable the Rex Codex hook for an exact transcript path")
    matches = []
    try:
        for root, dirs, files in os.walk(str(sessions), followlinks=False):
            dirs[:] = [directory for directory in dirs if not (Path(root) / directory).is_symlink()]
            for filename in files:
                if _codex_thread_id_matches(filename, thread_id):
                    candidate = Path(root) / filename
                    if candidate.is_file() and not candidate.is_symlink():
                        matches.append(candidate.resolve(strict=True))
    except OSError as error:
        raise ReplyError("cannot locate exact Codex thread transcript: {}".format(error))
    unique = sorted(set(matches))
    if not unique:
        raise ReplyError(
            "no JSONL rollout filename matches CODEX_THREAD_ID {}; enable the Rex Codex SessionStart hook to supply its exact transcript path".format(thread_id)
        )
    if len(unique) != 1:
        raise ReplyError(
            "multiple Codex rollouts match this thread; refusing to guess the active branch. Enable the Rex Codex SessionStart hook for an exact transcript path"
        )
    return str(unique[0])


def _env_token(name: str) -> str:
    return _require_token(os.environ.get(name), name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read oldest-first Rex assistant replies from an exact Codex or Claude session.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("replies", "validate"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--agent", choices=("codex", "claude"), required=True)
        sub.add_argument("--pid", type=int, required=True)
        sub.add_argument("--session", required=True, dest="rex_session")
        sub.add_argument("--block", required=True, dest="rex_block")
        if command == "validate":
            sub.add_argument("--conversation", required=True, dest="conversation_id")
    register = subparsers.add_parser("register")
    register.add_argument("--agent", choices=("codex", "claude"), required=True)
    register.add_argument("--pid", type=int, required=True)
    register.add_argument("--session", required=True, dest="rex_session")
    register.add_argument("--block", required=True, dest="rex_block")
    register.add_argument("--conversation", required=True, dest="conversation_id")
    register.add_argument("--transcript", required=True, dest="transcript_path")
    unregister = subparsers.add_parser("unregister")
    unregister.add_argument("--agent", choices=("codex", "claude"), required=True)
    unregister.add_argument("--pid", type=int, required=True)
    unregister.add_argument("--session", required=True, dest="rex_session")
    unregister.add_argument("--block", required=True, dest="rex_block")
    unregister.add_argument("--conversation", required=True, dest="conversation_id")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "register":
            record = register_binding(
                args.agent,
                args.pid,
                args.rex_session,
                args.rex_block,
                args.conversation_id,
                args.transcript_path,
            )
            print(json.dumps({"registered": True, "sessionId": record["conversation_id"]}, separators=(",", ":")))
            return 0
        if args.command == "unregister":
            removed = unregister_binding(
                args.agent,
                args.pid,
                args.rex_session,
                args.rex_block,
                args.conversation_id,
            )
            print(json.dumps({"unregistered": removed}, separators=(",", ":")))
            return 0
        if args.command == "validate":
            record = _verified_binding(
                args.agent,
                args.pid,
                args.rex_session,
                args.rex_block,
                args.conversation_id,
            )
            print(json.dumps({"valid": True, "sessionId": record["conversation_id"]}, separators=(",", ":")))
            return 0
        binding_path, record = _current_binding(args.pid, args.agent, args.rex_session, args.rex_block)
        if record.get("pending") is True and not Path(record["transcript_path"]).exists():
            replies = []  # New native sessions may not persist their file until the first turn.
        else:
            replies = _parse_transcript(args.agent, record["transcript_path"], record["conversation_id"])
        _ensure_binding_unchanged(binding_path, args.pid, record)
        print(json.dumps({"sessionId": record["conversation_id"], "replies": replies}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except ReplyError as error:
        print("rex-annotation: {}".format(error), file=sys.stderr)
        if str(error).startswith("no active reply binding"):
            print("Start the agent with bin/rex-annotation in its Rex pane. Codex also needs its rex-annotation skill or native hook activated.", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError) as error:
        print("rex-annotation: failed safely: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
