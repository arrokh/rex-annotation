# Documentation

[Project README](../README.md)

Rex Annotation turns selected agent-reply quotes into feedback. It runs in Rex,
uses Neovim for annotation, and targets the agent pane you started from.

## Start here

| Your task | Guide | What you will find |
| --- | --- | --- |
| First installation | [Setup](setup.md#homebrew) | Requirements, Homebrew, and source setup |
| Update an installation | [Upgrade](homebrew.md#install-or-upgrade) | Upgrade, rerun setup, and check status |
| Annotate a reply | [Usage](usage.md#annotate-a-reply) | Pick a reply, select a quote, and save a note |
| Find a shortcut | [Key reference](usage.md#key-reference) | Selection, notes, preview, copy, insert, and Send |
| Understand an error | [Troubleshooting](setup.md#common-fixes) | Status meanings and safe next steps |
| Check privacy or size limits | [Privacy and limits](usage.md#privacy-and-limits) | What is read, kept, and refused |
| Remove the integration | [Uninstall](setup.md#uninstall) | Remove only owned setup; preserve other settings |

## Agent guides

Plain `rex-annotation install` detects the supported CLIs. CUX uses the Claude
integration; it is not a fourth adapter.

- [Pi](../integrations/pi/README.md): package registration and the live bridge.
- [Codex CLI](../integrations/codex/README.md): hooks, scoped trust, and deferred startup.
- [Claude Code and CUX](../integrations/claude/README.md): hooks and wrapper/child binding.
- [Shared session-safety reference](../integrations/README.md): exact binding,
  native transcript formats, adapter protocol, and limits.

## Work on the project

- [Code map and tests](development.md): where behavior lives and which checks to run.
- [Release process](development.md#release-process): versioning, publication, and verification.
- [Homebrew packaging](homebrew.md#build-a-release-package): reproducible archive and formula.
- [Changelog](../CHANGELOG.md): shipped changes.

## Related tools and sources

[Related projects and references](related-tools.md) explains **Herdr Annotate**,
**Plannotator**, and **Plannotator TUI**, with links to their upstream guides.
They are separate tools, not required parts of this installation.

Need help? [Open an issue](https://github.com/arrokh/rex-annotation/issues).
Include the plugin version, agent name, exact error, and relevant status checks.
Do not include credentials or a full private transcript.
