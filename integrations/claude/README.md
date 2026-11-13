# Claude Code and CUX

[Project README](../../README.md) · [Documentation](../../docs/README.md) ·
[Agent index](../README.md)

## Normal setup

Plain `rex-annotation install` detects Claude and CUX. To select this integration
explicitly:

```sh
rex-annotation install --claude
```

Then start **`claude` or `cux` normally inside Rex**. No annotation launcher or
manual plugin load is required. Press **Ctrl+S, then o** to choose a reply.
[Usage](../../docs/usage.md) explains selection, comments, insert, and Send.

## Hooks and configuration

Setup merges owned lifecycle hooks into
`$CLAUDE_CONFIG_DIR/settings.json` (normally `~/.claude/settings.json`). Use the
same override for setup and the agent. Other hooks, permissions, authentication,
and explicit hook-disable/managed policies are preserved.

SessionStart/UserPromptSubmit bind the exact native session and transcript;
Stop refreshes metadata and SessionEnd removes only the matching registration.
Subagent events cannot replace a foreground binding. Existing processes are not
restarted or reloaded by installation.

## CUX uses the same adapter

CUX is a Claude launcher, not a fourth integration. Its foreground PTY wrapper
owns delivery; the native Claude child's PID/start identity owns transcript
validity. An exited child invalidates the old binding. A resumed child registers
again, and a delayed old SessionEnd cannot delete that new child's registration.

Account enrollment, credentials, refresh, and switching remain entirely under
CUX control. Rex Annotation does not run CUX account commands.

## Optional plugin launcher

This directory contains adapter code, **not a standalone Claude plugin**. The
repository root supplies `.claude-plugin/plugin.json`, `hooks/hooks.json`, and
the shared transcript reader.

The optional `./bin/rex-annotation claude` source launcher loads that root plugin
and preserves the native PID with `exec`. Normal installed user hooks are the
default workflow; do not load this subdirectory alone as a plugin.

**Next:** [Native transcript safety and limits](../README.md#privacy-limits-and-format-caveats) ·
[Troubleshooting](../../docs/setup.md#common-fixes) ·
[Uninstall owned hooks](../../docs/setup.md#uninstall)
