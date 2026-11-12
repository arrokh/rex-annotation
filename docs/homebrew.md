# Homebrew installation and packaging

## Install or upgrade

```sh
brew tap arrokh/rex-annotation https://github.com/arrokh/rex-annotation &&
brew install arrokh/rex-annotation/rex-annotation &&
rex-annotation install &&
rex-annotation status
```

For an existing installation using this tap:

```sh
brew update &&
brew upgrade arrokh/rex-annotation/rex-annotation &&
rex-annotation install &&
rex-annotation status
```

The [formula](../Formula/rex-annotation.rb) lives in this same repository and
uses a checksummed versioned [GitHub release](https://github.com/arrokh/rex-annotation/releases).
The explicit tap URL is needed because Homebrew otherwise assumes a separate
`homebrew-rex-annotation` repository. Future `brew update` calls retain this URL.
Brew installs Python and Neovim. Rex and the selected coding-agent CLIs must be
installed separately.

Brew installs program files only. User configuration is created by the explicit
setup command; there is no `post_install` modification of your home directory.
Plain `install` configures every detected supported agent, including its own Codex
hook approvals, and activates running Rex config. It never reloads an agent process.

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
  --source-url https://github.com/arrokh/rex-annotation/releases/download/v0.1.7/rex-annotation-0.1.7.tar.gz
```

Use the actual version from `package.json`. The generator produces:

- A reproducible `rex-annotation-VERSION.tar.gz` with the license and runtime files.
- Its SHA-256 printed on stdout.
- A formula using the matching release URL and computed checksum.

Only allowed project resources selected by Git are included; ignored caches,
local state, credentials, logs and generated packages stay out. Upload the exact
archive to the matching release, download it, and compare its SHA before updating
`Formula/rex-annotation.rb` in this repository. Never substitute an unverified
checksum or replace an existing release archive. The formula is excluded from
the archive to avoid a circular checksum dependency.

```sh
ruby -c dist/homebrew/rex-annotation.rb
brew ruby -e 'require "formula"; load ARGV.fetch(0); puts RexAnnotation.name' \
  "$PWD/dist/homebrew/rex-annotation.rb"
```

Also validate the committed `Formula/rex-annotation.rb` after updating it.
These validate Ruby/the DSL, not a full install. `brew test arrokh/rex-annotation/rex-annotation` also
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
