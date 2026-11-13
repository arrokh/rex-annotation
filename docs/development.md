# Development

[Project README](../README.md) · [Documentation](README.md)

[Run checks](#run-checks) · [Live checks](#optional-live-checks) ·
[Code map](#layout) · [Release](#release-process)

## Run checks

No `npm install` step is needed. The offline suite uses Node.js, Python, and
Neovim; have those system tools available first.

```sh
npm test
```

On macOS, use the same Python PATH as CI when possible:

```sh
export PATH="$(brew --prefix python@3.14)/libexec/bin:$PATH"
npm test
```

This also keeps interpreter shims from consuming the short startup deadline in
Codex's synthetic timeout tests. The suite uses disposable fixtures and does not
send real coding-agent prompts or modify your production configuration.

Useful focused checks, from the project root:

```sh
python3 -m unittest discover -s tests -p 'test_claude_parallel_tools.py'
python3 -m unittest discover -s tests -p 'test_docs_navigation.py'
python3 -m unittest discover -s integrations/tests -p 'test_*.py'
node --test integrations/pi/test/*.test.mjs
git diff --check
```

## Optional live checks

Run these deliberately, with local Rex running and the needed CLIs installed.
They create and delete their own Rex sessions; they are not tests of your live
work. Real-agent startup checks use disposable homes and deny network access.
Fake-agent checks do not start a real coding agent.

| Check | Command | What it verifies |
| --- | --- | --- |
| Full synthetic delivery | `python3 scripts/test-native-overlays.py` | Codex/Claude/CUX picker, comments, insert/Send, focus, and cleanup |
| One synthetic agent | `python3 scripts/test-native-overlays.py --agent cux` | Focused CUX child-restart and delivery checks; also accepts `claude` or `codex` |
| Real Claude startup | `python3 scripts/test-native-startup.py --agent claude` | Normal CLI and user-hook registration; no model prompt |
| Codex resumed startup | `python3 scripts/test-native-startup.py --agent codex --no-fixture-input` | Exact binding before new input, using synthetic saved history |
| Codex fresh startup | `python3 scripts/test-native-startup.py --agent codex --fresh-codex` | Deferred hooks with offline input to an unreachable fixture model |
| Error screen | `python3 scripts/test-startup-errors.py` | Safe multiline startup failures; no agent input |
| Clipboard | `swift scripts/test-rex-annotate-clipboard.swift` | Copy behavior; restores all original clipboard data types |

The native overlay fixtures include parallel tools, mixed tool-result context,
progress links, and CUX child rebinding. Keep those realistic shapes when adding
regressions; an empty startup or a linear chat cannot prove reply-history support.

For the Rex launcher/overlay itself:

```sh
python3 scripts/test-rex-annotate-live.py --overlay
python3 scripts/test-rex-annotate-live.py --overlay --installed --leave-focus
```

Actual Pi-vim/editor checks need your local unbundled Pi CLI and optional Pi-vim
extension paths. Supply them explicitly; do not embed machine-specific paths:

```sh
export REX_ANNOTATION_PI_ENTRY=/path/to/pi-coding-agent/dist/cli.js
export REX_ANNOTATION_PI_VIM=/path/to/pi-vim/index.ts
python3 scripts/test-rex-annotate-live.py --pi-vim --pi-bridge
python3 scripts/test-rex-annotate-live.py --agents
```

## Layout

| Change or investigate… | Start here |
| --- | --- |
| Rex action and pane launch | [`rex/annotate.lua`](../rex/annotate.lua) |
| Neovim picker, selection, notes, and help | [`rex/annotate_view.lua`](../rex/annotate_view.lua) |
| Source capture, target checks, and delivery | [`rex/annotate_core.lua`](../rex/annotate_core.lua) |
| Pi replies and editor operations | [`integrations/pi/`](../integrations/pi/README.md) |
| Native transcript parsing and binding records | [`integrations/session_replies.py`](../integrations/session_replies.py) |
| Native foreground/ancestor resolution | [`integrations/native_scope.py`](../integrations/native_scope.py) |
| Setup and diagnostics | [`scripts/install.py`](../scripts/install.py), [`scripts/status.py`](../scripts/status.py) |
| Scoped Codex hook trust | [`scripts/codex_setup.py`](../scripts/codex_setup.py) |
| Homebrew archive and formula | [`scripts/brew-package.py`](../scripts/brew-package.py), [`Formula/rex-annotation.rb`](https://github.com/arrokh/rex-annotation/blob/main/Formula/rex-annotation.rb) |
| Test entry point | [`scripts/test.sh`](../scripts/test.sh) and [`tests/`](../tests/) |
| Documentation navigation | [`docs/README.md`](README.md), [`tests/test_docs_navigation.py`](../tests/test_docs_navigation.py) |

The [agent guide](../integrations/README.md) explains the native adapter protocol,
metadata paths, format limits, and safety contract. Root `.claude-plugin/` and
`hooks/` form the optional Claude plugin; the Claude adapter subdirectory alone
is not a plugin package.

## Uninstall

See [uninstall steps](setup.md#uninstall). Remove only owned registration and
hooks; never delete native transcripts, unrelated config, or a live Pi socket.

## Release process

1. Run the checks above and inspect staged files for private/generated data.
2. Set the same version in `package.json`, `integrations/pi/package.json`, and
   `.claude-plugin/plugin.json`; update `CHANGELOG.md`.
3. Commit and review the implementation; require the relevant CI checks to pass.
4. [Build the reproducible package](homebrew.md#build-a-release-package) using
   the exact versioned public asset URL, and record its SHA-256.
5. Publish the tested commit/tag and upload that exact archive. Use
   `--title vX.Y.Z`; the title must exactly match the tag.
6. Download the public asset and verify its digest before updating
   `Formula/rex-annotation.rb`. Never rebuild or replace a published archive to
   update its formula; the formula is deliberately outside the archive.
7. Validate both formulas, run `brew test arrokh/rex-annotation/rex-annotation`,
   and perform a fresh-HOME setup smoke before advertising the release.
8. For a local upgrade, follow [upgrade and setup](homebrew.md#install-or-upgrade).
   Do not reload running coding agents or send a real prompt as a smoke test.

Publication uses the operator's authorized GitHub CLI configuration. No token
belongs in project files. CI runs the offline suite; live Rex tests are opt-in.

**Next:** [Homebrew packaging](homebrew.md) · [Agent internals](../integrations/README.md) ·
[Related projects and references](related-tools.md)
