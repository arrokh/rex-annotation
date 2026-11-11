# Development

No dependency install is needed for the offline unit tests:

```sh
npm test
```

The unit tests use only synthetic sessions, transcript fixtures, and service
callbacks. Optional live tests create/delete their own Rex sessions. They deny
network access and use disposable agent homes; no real agent prompt is sent:

```sh
python3 scripts/test-rex-annotate-live.py --overlay
python3 scripts/test-rex-annotate-live.py --overlay --installed --leave-focus
python3 scripts/test-native-overlays.py # fake Codex/Claude s/S, never real agents
python3 scripts/test-native-startup.py --agent claude # plain CLI + user hooks, no model requests
# --agent codex stops with exit 2 at an unapproved /hooks gate
swift scripts/test-rex-annotate-clipboard.swift # restores all clipboard data types
```

For actual Pi-vim/editor checks, explicitly provide your local unbundled Pi CLI
and optional pi-vim extension paths (no machine-specific paths are embedded):

```sh
export REX_ANNOTATION_PI_ENTRY=/path/to/pi-coding-agent/dist/cli.js
export REX_ANNOTATION_PI_VIM=/path/to/pi-vim/index.ts
python3 scripts/test-rex-annotate-live.py --pi-vim --pi-bridge
python3 scripts/test-rex-annotate-live.py --agents
```

## Layout

```text
Formula/             Published Homebrew formula, maintained in this same repository
bin/                 Setup/status CLI and optional explicit native launchers
.claude-plugin/      Root Claude Code plugin manifest
hooks/               Root Claude Code lifecycle configuration
rex/                 Rex launcher, in-memory core, Neovim UI
integrations/pi/     Pi package and private live editor/reply bridge
integrations/        Codex/Claude registration and native transcript adapters
scripts/             Local installer and synthetic/live checks
tests/               Adapter and installer regression tests
```

## Uninstall

Remove the loader line/file and the Codex skill symlink you installed. Remove
the Pi package with `pi remove /absolute/path/to/rex-annotation`, and disable
or uninstall the Claude plugin if enabled. Reload Rex config only after checking
it. Do not delete native agent transcripts, unrelated config, or another live
Pi process's socket. Native integration guide documents owned metadata cleanup.

## Release process

1. Run `npm test` and review the staged files for private/generated data.
2. Choose a version in `package.json` and update `CHANGELOG.md`.
3. Build the reproducible archive with `scripts/brew-package.py --source-url` set
   to the exact versioned GitHub release asset URL; verify its SHA-256.
4. Publish the tested commit/tag and upload the archive to the matching GitHub release.
5. Download the public asset and verify its digest before updating `Formula/rex-annotation.rb`
   in this repository. Do not rebuild/replace a published archive to update its formula.
6. Run `brew test arrokh/rex-annotation/rex-annotation` and a fresh-HOME setup smoke
   before advertising the release.

Publication uses the operator's authorized GitHub CLI configuration. No token is
stored in project files. CI runs offline unit tests; live Rex tests are opt-in.
