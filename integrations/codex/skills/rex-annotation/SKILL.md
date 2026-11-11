---
name: rex-annotation
description: Register the exact active Codex CLI thread so Rex Annotation can show its assistant replies. Use when starting or resuming a Rex Codex session, or when Rex reports that no Codex session is bound.
---

# Register this Codex session with Rex

Run the registration helper from the Rex Bash tool shell:

```bash
if [ -z "${REX_ANNOTATION_ROOT:-}" ]; then
  echo "Start the next Codex session with /path/to/rex-annotation/bin/rex-annotation codex in its Rex pane." >&2
  exit 1
fi
python3 "$REX_ANNOTATION_ROOT/integrations/codex/skills/rex-annotation/scripts/register_current.py"
```

The helper uses Codex's `CODEX_THREAD_ID` and matches only rollout filenames for that exact thread. It writes metadata only; it does not copy the transcript. If more than one rollout matches, report the error and ask the user to enable the Rex Codex SessionStart hook so Codex supplies its exact active transcript path. Never choose the newest rollout by timestamp or guess a session id.

Report whether registration succeeded, then stop. If the binding environment is missing, tell the user how to launch their next session; leave the current process untouched. Do not print transcript text while registering.
