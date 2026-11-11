# Homebrew installation and packaging

## Install or upgrade

```sh
brew install arrokh/tap/rex-annotation
rex-annotation install --detect --reload-rex
rex-annotation status
```

For an existing installation:

```sh
brew update
brew upgrade rex-annotation
rex-annotation status
```

The [tap](https://github.com/arrokh/homebrew-tap) uses the versioned archive from
[GitHub releases](https://github.com/arrokh/rex-annotation/releases), with its
real SHA-256 checksum and MIT license. Brew installs Python and Neovim. Rex and
the selected coding-agent CLIs must be installed separately.

Brew installs program files only. User configuration is created by the explicit
setup command; there is no `post_install` modification of your home directory.
`--reload-rex` validates and activates Rex config, never an agent process.

## Upgrade-safe paths

The Brew executable exports `REX_ANNOTATION_ROOT` through the stable
`$(brew --prefix)/opt/rex-annotation/libexec` path. Generated loaders, Pi package
registrations and Codex hooks use this root instead of a versioned Cellar path.

If migrating from a custom source-checkout loader, review the path mismatch
reported by `status`; setup does not overwrite an unrelated/custom loader.
Remove an old source-install CLI symlink from `~/.local/bin` only if you own it
and deliberately want the Brew executable to take precedence on PATH.

## Build a release package

From a Git checkout:

```sh
python3 scripts/brew-package.py \
  --source-url https://github.com/arrokh/rex-annotation/releases/download/v0.1.1/rex-annotation-0.1.1.tar.gz
```

Use the actual version from `package.json`. The generator produces:

- A reproducible `rex-annotation-VERSION.tar.gz` with the license and runtime files.
- Its SHA-256 printed on stdout.
- A formula using the matching release URL and computed checksum.

Only allowed project resources selected by Git are included; ignored caches,
local state, credentials, logs and generated packages stay out. Upload the exact
archive to the matching release, download it, and compare its SHA before updating
`Formula/rex-annotation.rb` in the tap. Never substitute an unverified checksum.

```sh
ruby -c dist/homebrew/rex-annotation.rb
brew ruby -e 'require "formula"; load ARGV.fetch(0); puts RexAnnotation.name' \
  "$PWD/dist/homebrew/rex-annotation.rb"
```

These validate Ruby/the DSL, not a full install. `brew test rex-annotation` also
checks fresh-HOME setup/status with a fake Rex CLI and real packaged dependencies.
It does not send coding-agent requests or modify production user configuration.

## Local development formula

To test a checkout without publishing another release:

```sh
./scripts/install-homebrew
# after changing source:
./scripts/install-homebrew --reinstall
```

This builds a checksummed `file://` archive and an owned `local/rex-annotation`
tap. Keep `dist/homebrew` while using that development formula. The helper refuses
to overwrite an unowned tap/formula. `--prepare-only` generates files without
changing Homebrew.

See [release process](development.md#release-process) and [setup](setup.md).
