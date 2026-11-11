# Setup and troubleshooting

## Required tools

| Tool | How it is provided |
| --- | --- |
| macOS and Rex, including the `rex` CLI | Install Rex separately |
| Neovim with `vim.system` and `getregion` (0.12.x tested) | Brew installs `neovim` automatically |
| Python 3.9+ | Brew installs `python@3.14` automatically |
| Pi, Codex CLI 0.167.1+, or Claude Code/CUX | Install only the agent CLIs you intend to use |

Neovim is required: classic `vi` and Vim are not compatible fallbacks. The UI
uses Neovim's Lua APIs, floating windows and text highlights. Missing Neovim is
reported by `rex-annotation status`; setup does not silently switch editors.
Node.js is part of the Pi runtime when using Pi; native Codex/Claude adapters
need only the Python dependency. A C compiler is needed only for the optional
fake-native E2E developer test, not normal plugin use.

## Homebrew

```sh
brew tap arrokh/rex-annotation https://github.com/arrokh/rex-annotation &&
brew install arrokh/rex-annotation/rex-annotation &&
rex-annotation install &&
rex-annotation status
```

The [formula](../Formula/rex-annotation.rb) lives in this same repository. The
explicit tap URL is required because the repo is not named `homebrew-*`. Brew
installs code, Python and Neovim; it does not write to your user configuration.
Install Rex and the coding-agent CLIs separately.

## Source checkout

```sh
git clone https://github.com/arrokh/rex-annotation.git
cd rex-annotation
./bin/rex-annotation install
rex-annotation status
```

Source setup links the CLI into `~/.local/bin`; add that directory to PATH if
your shell does not already include it.

## Setup options

Plain `install` configures Rex and every supported agent CLI detected on PATH:
Pi, Codex, and Claude Code (including CUX). It enables the Codex hooks feature,
trusts only this integration's exact hook definitions, and verifies readiness.
No extra approval prompt, `--trust-hooks` option, or manual `/hooks` step is needed.

Selection options remain available for deliberately scoped setup:

| Option | Behavior |
| --- | --- |
| `--detect` | Explicit spelling of the default agent detection |
| `--rex` | Configure Rex only unless other selections are supplied |
| `--pi` | Register the root Pi package using `pi install` |
| `--codex` | Link its skill, merge lifecycle hooks, enable and trust only owned hooks |
| `--claude` | Merge owned lifecycle hooks into Claude user settings |
| `--all` | Select all three integrations; selected dependencies must exist |
| `--reload-rex` | Require running Rex; compatibility option for config activation |

Setup automatically checks and reloads running Rex config, then verifies the
annotation action. If Rex is stopped, its saved config loads on the next launch;
setup does not start Rex. Existing coding-agent processes are never reloaded.

Setup never installs an agent CLI, changes authentication or sandbox/tool-approval
policy, or sends a model request. Codex configuration uses an isolated config-only
app-server process with networking denied; no coding-agent thread is started. Repeating setup is safe;
unrelated config/hooks remain intact. Unknown existing files are not overwritten.
Unsupported Codex versions, failed verification, and hook-policy blockers return
nonzero instead of claiming the integration is ready.

### Native agents: normal commands

After `install`, start `codex`, `claude`, or `cux`
normally in a Rex pane. CUX counts as Claude during detection and diagnostics,
including installations where only `cux` is on PATH. No aliases, PATH shims, or special launchers are required. The
hooks bind the exact foreground process and hook-provided conversation; outside
Rex they do nothing. Setup never restarts an existing native agent.

Codex hooks live in `$CODEX_HOME/hooks.json` (default `~/.codex/hooks.json`).
Claude hooks live in `$CLAUDE_CONFIG_DIR/settings.json` (default
`~/.claude/settings.json`). Only this integration's handlers are merged; other
settings and hooks remain intact. Run setup with the same configuration-directory
environment as the agent. Explicitly disabled hooks and organization policy are
not overridden. CUX keeps ownership of its accounts, credentials and switching;
setup does not run CUX account commands. Codex approval is persisted only for
this integration's definitions through Codex's own hook/config API. Other hooks
are never automatically trusted, and no trust-bypass flags are used.

## Rex loader

The canonical module is `require("rex-annotation")`. Its file at
`~/.config/rex/rex-annotation.lua` loads this project's `rex/annotate.lua`.
Old managed module names migrate without loading the action twice.

A source loader records the checkout; a Brew loader uses its stable `opt` path,
not a versioned Cellar directory. Custom consumer-managed loaders may require
an explicit path update when moving between a source checkout and Brew. Status
reports a mismatch instead of overwriting a custom loader.

The only key binding is `Ctrl+S, then o`. The palette action is **Annotate Agent
Reply or Terminal Output**.

## Status and doctor

```sh
rex-annotation status
rex-annotation status --json
rex-annotation doctor
```

These commands do not change settings, hook approvals, or loaded agent runtimes.
They check the CLI, Python, Neovim features, Rex loader/init/config/live action,
and agent registration. Codex may create its normal local logs/cache while its
network-denied config process reads native hook state.

- **ok**: the observable checks passed.
- **attention**: setup checks passed, but an existing agent's loaded runtime or
  managed policy cannot be observed. This is not a failed install.
- **fail**, exit code 1: a required check failed. Follow the printed fix.

Use `status --pi`, `--codex`, or `--claude` to require a particular integration.
A registered Pi package with its extension disabled is not reported healthy.

## Common fixes

- **CLI missing:** add `~/.local/bin` to PATH after source install; Brew installs
  it into the Brew bin directory.
- **Rex action missing:** run `rex config check`, then `rex config reload`.
- **Codex hook readiness:** rerun `rex-annotation install`. It enables and trusts
  only its own hooks and verifies the result. If the config API is unsupported,
  upgrade Codex; explicit hook-disable or managed policies are reported, not bypassed.
- **Pi bridge not loaded:** an existing process retains its loaded extension.
  Only reload for bridge changes after checking session-auth effects. Do not
  reload a working session just to clear an informational status check.
- **Native reply history unavailable:** run `rex-annotation install`,
  then start a new normal `codex`, `claude`, or `cux` process inside
  Rex. Match any `CODEX_HOME`/`CLAUDE_CONFIG_DIR` override used at setup; see the
  [integration guide](../integrations/README.md).
- **Delivery timeout:** inspect the original draft before retrying. The operation
  may already have happened; the plugin never retries it automatically.
