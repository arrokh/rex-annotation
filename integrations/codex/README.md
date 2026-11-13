# Codex CLI

[Project README](../../README.md) · [Documentation](../../docs/README.md) ·
[Agent index](../README.md)

## Normal setup

Use Codex CLI **0.167.1 or newer** with the required native hook/config APIs.
Plain `rex-annotation install` detects Codex. To select it explicitly:

```sh
rex-annotation install --codex
```

Then start **`codex` normally inside Rex** and press **Ctrl+S, then o**.
No alias, PATH shim, special launcher, or manual hook approval is needed.
[Usage](../../docs/usage.md) covers the annotation workflow.

## What setup owns

- A `rex-annotation` skill link under `~/.agents/skills/`.
- Its lifecycle handlers in `$CODEX_HOME/hooks.json` (normally `~/.codex/hooks.json`).
- The hooks feature and native trust for **only those exact hook definitions**.

Setup obtains the current hook keys/hashes from Codex's own API, persists only
owned trust, and verifies it. The config-only app-server is bounded and
network-denied; it does not start a coding-agent thread or model request.

Other hooks, explicit disables, organization policy, authentication, and
sandbox/tool-approval settings remain intact. Unsupported APIs or policy blockers
are reported instead of bypassed. Use the same `CODEX_HOME` for setup and Codex.

## Deferred startup and saved replies

Codex can defer lifecycle hooks until the first prompt. Before new input, a
resumed thread can still be bound when exactly one canonical rollout is open by
the **exact Rex foreground Codex PID**. The reader verifies its thread identity
and transcript; missing or multiple candidates fail rather than picking a file
by modification time.

A brand-new session may not have a saved reply yet. Installation does not
restart an existing Codex process, send a prompt, or change daemon preferences.
Remote/shared-daemon hooks outside the local foreground ancestry fail closed;
see [automatic Rex binding](../README.md#automatic-rex-binding).

## Advanced fallbacks

The optional `rex-annotation codex` launcher and `$rex-annotation` skill remain
available. The skill uses `CODEX_THREAD_ID` to match one exact canonical rollout;
it is not a newest-session lookup. Prefer native hooks for automatic tracking
across conversation changes. See the [activation reference](../README.md#codex-cli).

**Next:** [Session protocol and limits](../README.md) ·
[Codex readiness fixes](../../docs/setup.md#common-fixes) ·
[Uninstall owned hooks](../../docs/setup.md#uninstall)
