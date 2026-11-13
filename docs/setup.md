# Setup and troubleshooting

[Project README](../README.md) · [Documentation](README.md) · [Usage](usage.md)

[Requirements](#required-tools) · [Install](#homebrew) ·
[Source](#source-checkout) · [Status](#status-and-doctor) ·
[Fix a problem](#common-fixes) · [Options](#setup-options) · [Remove](#uninstall)

## Required tools

| Tool | How you get it |
| --- | --- |
| macOS and Rex, including the `rex` CLI | Install Rex separately |
| Neovim with `vim.system` and `getregion` (0.12.x tested) | Homebrew installs `neovim` |
| Python 3.9+ | Homebrew installs `python@3.14` |
| Pi, Codex CLI 0.167.1+, or Claude Code/CUX | Install only the agent CLIs you use |

**Neovim is required.** Classic `vi` and Vim are not fallbacks: the UI needs
Neovim's Lua APIs, floating windows, and selection functions. Pi uses its normal
Node.js runtime; native Codex/Claude adapters need Python. A C compiler is needed
only for the optional fake-agent developer tests, not normal use.

Herdr Annotate and Plannotator are separate projects, not prerequisites. See
[related tools](related-tools.md) if you are looking for those workflows.

## Homebrew

```sh
brew tap arrokh/rex-annotation https://github.com/arrokh/rex-annotation &&
brew install arrokh/rex-annotation/rex-annotation &&
rex-annotation install &&
rex-annotation status
```

The [formula](https://github.com/arrokh/rex-annotation/blob/main/Formula/rex-annotation.rb) is in this repository. The explicit
tap URL is needed because the repository is not named `homebrew-*`.

Homebrew installs program files and dependencies. The separate
`rex-annotation install` command writes your integration settings. It detects
supported agent CLIs on PATH; you do not need to install all three agents.

For an existing installation, use [upgrade steps](homebrew.md#install-or-upgrade).

## Source checkout

```sh
git clone https://github.com/arrokh/rex-annotation.git
cd rex-annotation
./bin/rex-annotation install
./bin/rex-annotation status
```

Use `./bin/rex-annotation` for checkout-specific commands. Setup can link the CLI
into `~/.local/bin`, but it keeps an existing CLI on PATH, such as Homebrew's,
when appropriate. Add `~/.local/bin` to PATH if you use that source-install link.

Avoid mixing installation roots accidentally. [Status](#status-and-doctor)
reports a loader/path mismatch instead of overwriting a custom consumer loader.

## What setup changes

| Integration | Owned setup |
| --- | --- |
| Rex | Loader and init reference; check/reload running Rex config and verify the action |
| Pi | Register the root package through `pi install`; verify package/extension registration |
| Codex | Skill link, lifecycle hooks, hooks feature, and native trust for only the exact owned hook definitions |
| Claude/CUX | Owned lifecycle hooks merged into Claude user settings |

Repeating setup is safe. Unrelated hooks and settings remain intact. Unknown
existing files are not overwritten. Explicit hook-disable and organization
policies are reported as blockers, not bypassed.

Setup does **not** install an agent CLI, change authentication or sandbox/tool
approval policy, start a model request, or reload an agent process. CUX retains
control of its accounts, credentials, refresh, and switching.

If Rex is running, only its configuration is reloaded. If it is stopped, setup
saves configuration for the next launch without starting Rex. Codex trust uses a
bounded, network-denied config-only app-server; no coding-agent thread starts.

## Native agents: normal commands

After setup, start `codex`, `claude`, or `cux` normally inside Rex. CUX uses the
Claude integration, even when only `cux` is on PATH. No aliases, PATH shims, or
annotation wrapper are required. Hooks outside Rex do nothing.

Start a new agent process deliberately when you need it to load newly installed
hooks or a Pi bridge. Installation leaves existing processes alone; do not
reload a working session merely to clear an informational status check.

Use the same configuration-directory environment for setup and the agent:

| Agent | Configuration |
| --- | --- |
| Codex | `$CODEX_HOME/hooks.json`, normally `~/.codex/hooks.json` |
| Claude/CUX | `$CLAUDE_CONFIG_DIR/settings.json`, normally `~/.claude/settings.json` |

Codex can defer hooks until its first prompt. A resumed thread can still work
before new input when exactly one valid rollout is open by that exact foreground
Codex PID. Missing or multiple candidates are refused; the plugin never guesses
the newest transcript. A new session may simply have no saved reply yet.

See the [Pi](../integrations/pi/README.md), [Codex](../integrations/codex/README.md),
and [Claude/CUX](../integrations/claude/README.md) guides for agent-specific details.

## Status and doctor

```sh
rex-annotation status
rex-annotation status --json
rex-annotation doctor
```

These checks do not change settings, approvals, or loaded agent runtimes. They
inspect tools, the Rex loader/config/action, and agent registration. Codex may
create normal local cache/log files while its network-denied config process
reads native hook state.

| Result | Meaning | Next step |
| --- | --- | --- |
| `ok` | The observable checks passed | Open the annotation action |
| `attention` | Setup checks passed, but an existing runtime or managed policy is not observable | Read the named check; this alone is not a failed install |
| `fail`, exit code 1 | A required check failed | Follow the printed fix |

Use `status --pi`, `--codex`, or `--claude` to require one integration. A registered
Pi package whose extension is explicitly disabled is not reported healthy.

## Common fixes

| Symptom | Safe next step |
| --- | --- |
| CLI missing | Check PATH. Source links use `~/.local/bin`; Homebrew uses its bin directory. |
| Rex action missing | Run `rex config check`, then `rex config reload`. This reloads Rex config, not agents. |
| Codex hooks not ready | Rerun `rex-annotation install`; it trusts only its own hooks. Upgrade unsupported Codex versions. Do not bypass explicit policy. |
| Pi bridge not loaded | Start a new Pi process, or deliberately reload only after reviewing session-only auth effects. Existing processes keep their loaded extension. |
| No native reply binding | Check the configuration-directory overrides used by setup and the agent. New processes should run normally in a Rex pane. |
| Claude/CUX ambiguous branch | Update the plugin first. If it persists, report the exact error and pane/session metadata: the adapter cannot prove one conversation. Do not rewrite the transcript or choose a file by recency. |
| History exceeds a limit | See [input limits](usage.md#privacy-and-limits); the plugin refuses partial history rather than silently truncating it. |
| Paste/Send timeout | Inspect the original draft before retrying. The operation may already have happened; automatic retries are disabled. |

When reporting a problem, include `rex-annotation --version`, the agent name,
error text, and the relevant status checks. Do not post credentials or an entire
private transcript. [Open an issue](https://github.com/arrokh/rex-annotation/issues).

## Setup options

Plain `install` detects supported CLIs. Use these only when you want a narrower
selection or an explicit dependency check:

| Option | Behavior |
| --- | --- |
| `--detect` | Explicit spelling of default agent detection |
| `--rex` | Configure Rex only unless other selections are supplied |
| `--pi` | Register and verify the root Pi package |
| `--codex` | Merge lifecycle hooks, enable hooks, and trust only owned definitions |
| `--claude` | Merge owned Claude lifecycle hooks; also used for CUX |
| `--all` | Select all three integrations; selected dependencies must exist |
| `--reload-rex` | Require running Rex; compatibility option for config activation |

No `--trust-hooks` flag, installer approval prompt, or manual `/hooks` step is
needed. Unsupported APIs, failed verification, and policy blockers return
nonzero instead of claiming readiness.

## Rex loader

The canonical module is `require("rex-annotation")`. Its loader at
`~/.config/rex/rex-annotation.lua` loads this project's `rex/annotate.lua`.
Old managed module names migrate without loading the action twice.

A source loader records its checkout. A Homebrew loader uses the stable `opt`
path, not a versioned Cellar directory. Custom consumer-managed loaders are not
overwritten; review a reported path mismatch when moving between installs.

The key sequence is **Ctrl+S, then o**. The palette action is **Annotate Agent
Reply or Terminal Output**.

## Uninstall

There is no automatic uninstall command. Remove only the entries owned by the
installation you selected; preserve unrelated configuration and credentials.

1. Remove that exact Pi package registration with `pi remove /exact/package/root`
   if you installed it. Do not remove every Pi package or a live bridge socket.
2. Remove only Rex Annotation's handlers from Codex `hooks.json` and Claude
   `settings.json`, in the same config directories used at setup. Owned commands
   point to this package's `integrations/codex/hooks/register.py` or
   `integrations/claude/hooks/register.py`. Preserve other handlers, settings,
   approvals, and policy; do not clear Codex's trust state globally.
3. Remove the Codex `rex-annotation` skill link only if it points to this package.
   If you separately enabled the root Claude plugin, disable only that plugin.
4. Remove this module's Rex init reference and its managed loader, not the whole
   Rex configuration. Treat custom consumer loaders as user-owned files.
5. Check and reload Rex configuration after that cleanup. Do not restart or
   reload coding-agent sessions automatically.
6. If using Homebrew, remove the program with
   `brew uninstall arrokh/rex-annotation/rex-annotation`. Remove a source CLI
   symlink only if it points to the checkout you intended to remove.

Keep native agent transcripts and other live session bindings intact. Normal
shutdown cleans up owned native registrations; force-kill can leave private
metadata that cannot match a new process with a different start identity.

**Next:** [Use the annotation pane](usage.md) · [Agent/session reference](../integrations/README.md) ·
[Homebrew guide](homebrew.md)
