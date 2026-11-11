---
name: rex-annotation
description: Register the exact active Codex CLI thread as a fallback when Rex Annotation reports no bound Codex session.
---

# Register this Codex session with Rex

Native lifecycle hooks normally register sessions automatically. If Codex is
waiting for hook approval, ask the user to review `/hooks` and stop; approval
remains theirs.

Otherwise, run the installed helper from this Codex session's Bash tool shell:

```bash
python3 "$HOME/.agents/skills/rex-annotation/scripts/register_current.py"
```

The helper uses Codex's `CODEX_THREAD_ID` and matches only rollout filenames for that exact thread. It writes metadata only; it does not copy the transcript. If more than one rollout matches, report the error and ask the user to enable the Rex Codex SessionStart hook so Codex supplies its exact active transcript path. Never choose the newest rollout by timestamp or guess a session id.

The helper verifies the exact Rex foreground process and conversation; it also
supports ordinary `codex` launches without a wrapper. Report success or the exact
error, then stop. If Rex context is missing, ask the user to start Codex inside
Rex; leave the current process untouched. Keep transcript text out of the report.
