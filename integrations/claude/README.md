# Claude Code hook adapter

This folder holds implementation code, not an independently installable plugin.
The standalone repository root is the Claude plugin: `.claude-plugin/plugin.json`
and `hooks/hooks.json` load this adapter with the shared `session_replies.py`
still inside the plugin package.

Run `bin/rex-annotation claude` from the project root in the source Rex pane.
The launcher preserves Claude's PID and loads the root plugin. Lifecycle hooks
bind the exact native session/transcript, refresh on prompts and Stop, and remove
only their own session's registration on normal exit. Subagents are ignored.

See [activation, limits, and privacy](../README.md).
