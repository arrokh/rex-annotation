# Related projects and references

[Project README](../README.md) · [Documentation](README.md)

Several projects use annotation to make agent feedback more precise. They run
in different places and have separate installation and state. This page is a
map, not a shared setup procedure.

## Choose by workflow

| You want to… | Project | Review surface |
| --- | --- | --- |
| Quote a reply from Pi, Codex, or Claude/CUX inside Rex | [Rex Annotation](../README.md) | Neovim in Rex |
| Annotate terminal text or review documents/replies inside Herdr | [Herdr Annotate](https://github.com/plannotator/herdr-annotate) | Herdr plugin; Full document review uses Plannotator TUI |
| Review plans, documents, artifacts, diffs, or PRs in a browser | [Plannotator](https://github.com/backnotprop/plannotator) | Local browser-based review surface |
| Review Markdown files, folders, or agent replies in a terminal | [Plannotator TUI](https://github.com/plannotator/plannotator-tui) | Standalone terminal UI |

## Herdr Annotate

[Herdr Annotate's upstream guide](https://github.com/plannotator/herdr-annotate)
describes terminal annotations, document review, agent-reply review, and feedback
delivery in **Herdr**. Its Full document-review workflow uses **Plannotator TUI**;
its Lite install has a smaller terminal-annotation workflow.

Use that guide for Herdr requirements, Full/Lite choices, key bindings, updates,
and its Neovim selection handoff. Herdr plugin actions are not Rex actions.
Installing Rex Annotation does not configure Herdr or install Herdr Annotate.

## Plannotator

[Plannotator](https://github.com/backnotprop/plannotator) is a local,
browser-based review surface for coding agents. It covers plans, documents,
interactive artifacts, code diffs, and pull requests. Agent integrations send
review feedback back to the agent.

Start with its [official site](https://plannotator.ai/) or
[upstream README](https://github.com/backnotprop/plannotator) for supported
integrations and current setup. This is distinct from the terminal TUI below.

## Plannotator TUI

[Plannotator TUI's upstream guide](https://github.com/plannotator/plannotator-tui)
covers standalone Markdown file/folder review, agent-reply review, selection,
notes, and feedback delivery. It can run outside Herdr and also powers Herdr
Annotate's Full document-review workflow.

Use its current guide for supported platforms, installation, keys, storage,
and delivery behavior. Those details can change between releases; Rex
Annotation does not replace its configuration or promise the same shortcuts.

## Relationship to Rex Annotation

- Rex Annotation's current UI uses **Neovim**, not Plannotator TUI.
- Herdr Annotate, Plannotator, and Plannotator TUI are **not dependencies** of
  this package. `rex-annotation install` does not install or configure them.
- Annotation formats, persistence, permissions, and delivery behavior belong to
  each project. Shared concepts do not imply automatic sync or interoperability.
- For this project's temporary notes, exact-session targeting, and insert/Send
  behavior, use [Usage](usage.md) and the [session-safety guide](../integrations/README.md).

Descriptions above are based on the linked upstream guides, not a compatibility
test between projects. Follow each project's own documentation for its current
features and requirements.
