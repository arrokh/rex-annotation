# Rex Annotation

Select a coding-agent reply in [Rex](https://www.superlogical.com/rex), highlight a
quote, and write feedback in Neovim. Supports **Pi, Codex CLI, and Claude Code**.

macOS · [MIT](LICENSE)

## Install

```sh
brew tap arrokh/rex-annotation https://github.com/arrokh/rex-annotation &&
brew install arrokh/rex-annotation/rex-annotation &&
rex-annotation install --detect --reload-rex &&
rex-annotation status
```

**Neovim is required; there is no vi/Vim fallback.** Brew installs Neovim and Python.
Install Rex (including its CLI) and your chosen agent CLIs separately.
Setup detects installed agents and reloads **Rex config only**—never Pi or another
agent. Codex hook approval remains manual in `/hooks`.

[Migrate an old tap](docs/homebrew.md#migrate-from-the-old-tap) or see [source setup](docs/setup.md).

## Use

Press **Ctrl+S, then o** in your agent pane. Pick a reply, select a quote with
`v`/`V`, and press **Enter** to comment. Save with **Ctrl+S**.

| Key | Action |
| --- | --- |
| `s` | Insert into the agent draft without submitting, then close |
| `S` | **Send immediately**, then close |
| `p` / `y` | Preview / copy the annotations |
| `m` | Edit or remove a note |
| `q` | Close; confirm before discarding unfinished work |

For native agents, start from the source Rex pane:

```sh
rex-annotation codex
rex-annotation claude
```

Delivery failures keep your notes open. [Full workflow and safety notes](docs/usage.md).

## Documentation

- [Setup, options, and troubleshooting](docs/setup.md)
- [Agent activation and exact-session limits](integrations/README.md)
- [Homebrew packaging and upgrades](docs/homebrew.md)
- [Development, tests, and releases](docs/development.md)

[Report a bug](https://github.com/arrokh/rex-annotation/issues).
