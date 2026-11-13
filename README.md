# Rex Annotation

**Quote an agent's reply, add comments, and send clear feedback from Neovim.**

Runs inside [Rex](https://www.superlogical.com/rex) on macOS. Supports **Pi,
Codex CLI, and Claude Code, including Claude launched through CUX**.

[Install](#install) · [Use](#use) · [Troubleshoot](docs/setup.md#common-fixes) ·
[All docs](docs/README.md) · [Related projects](docs/related-tools.md)

## Install

```sh
brew tap arrokh/rex-annotation https://github.com/arrokh/rex-annotation &&
brew install arrokh/rex-annotation/rex-annotation &&
rex-annotation install &&
rex-annotation status
```

Install **Rex and your chosen agent CLI** separately. Homebrew supplies Python
and **Neovim**; classic `vi` and Vim are not compatible substitutes.

`rex-annotation install` configures the supported agents it finds on PATH. It
trusts only its own Codex hooks and reloads **Rex configuration only**, never a
running agent. No extra setup flags or manual hook approval are needed. Explicit
hook-disable and organization policies are respected.

Already installed? See [upgrade steps](docs/homebrew.md#install-or-upgrade).
Prefer a checkout? See [source setup](docs/setup.md#source-checkout).

## Use

1. Start `pi`, `codex`, `claude`, or `cux` normally in a Rex pane after setup.
2. Press **Ctrl+S, then o**. Pick a reply with `j`/`k` and **Enter**.
3. Select a quote with `v` or `V`, then **Enter** to comment. **Ctrl+S** saves the
   comment. Enter without a selection comments on the current logical line.
4. Choose what to do with the feedback:

| Key | Result |
| --- | --- |
| `s` | Insert into the original agent's draft **without submitting** |
| `S` | **Send immediately** to the original agent |
| `p` / `y` | Preview / copy the feedback |
| `m` | Edit or remove a saved note |
| `q` | Close; confirm before discarding unfinished notes |

Successful insert or Send closes the annotation pane. A failure keeps your
notes open. Codex/Claude/CUX must be at an editable prompt; lowercase `s` asks
for confirmation before pasting. **Uppercase `S` does not ask for a typed SEND.**

The target is the saved pane and conversation, not whichever pane later gets
focus. The plugin refuses ambiguous native history instead of guessing a
session. Existing agent processes are not restarted by installation.

[Full workflow and key reference](docs/usage.md) ·
[Privacy and limits](docs/usage.md#privacy-and-limits)

## Find the right guide

| I want to… | Read |
| --- | --- |
| Browse all documentation | [Documentation index](docs/README.md) |
| Install, check setup, or diagnose an error | [Setup and troubleshooting](docs/setup.md) |
| Select text, manage notes, insert, or Send | [Usage](docs/usage.md) |
| Understand Pi, Codex, or Claude/CUX setup | [Agent integration guide](integrations/README.md) |
| Upgrade or understand Homebrew packaging | [Homebrew guide](docs/homebrew.md) |
| Find code, run tests, or publish a release | [Development guide](docs/development.md) |
| See what changed | [Changelog](CHANGELOG.md) |

## Related projects

- [Herdr Annotate](https://github.com/plannotator/herdr-annotate): terminal text,
  document, and agent-reply review inside **Herdr**.
- [Plannotator](https://github.com/backnotprop/plannotator): a local
  **browser-based** review surface for plans, documents, artifacts, and code.
- [Plannotator TUI](https://github.com/plannotator/plannotator-tui):
  **terminal-based** Markdown and reply review; also used by Herdr Annotate's
  Full document-review workflow.

These are separate tools, not dependencies installed by Rex Annotation.
[Which tool fits which workflow?](docs/related-tools.md)

[Report a bug](https://github.com/arrokh/rex-annotation/issues) ·
[Releases](https://github.com/arrokh/rex-annotation/releases) · [MIT license](LICENSE)
