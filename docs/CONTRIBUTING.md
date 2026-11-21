# Contributing

[Project README](../README.md) · [Documentation](README.md) · [Development guide](development.md)

Bug reports, documentation fixes, and small pull requests are welcome. For a
larger change, open an issue first to agree on the problem and scope.

## Report a bug

Use the [bug report template](https://github.com/arrokh/rex-annotation/issues/new?template=bug_report.md).
Include your macOS and tool versions, how you installed the plugin, steps to
reproduce, and what you expected. Include only the relevant, redacted lines of
`rex-annotation status`. Prefer a synthetic agent reply over a private transcript.

For security issues, follow the [security policy](SECURITY.md) instead.

## Open a pull request

1. Fork and clone the repository, then create a branch from `main`.
2. Make one focused change. If it changes setup, shortcuts, or privacy behavior,
   update the relevant guide. For a bug fix, add a synthetic regression test
   when practical.
3. Run `npm test` and `git diff --check` from the repository root. See the
   [development guide](development.md#run-checks) for prerequisites. You do not
   need to install the plugin into your normal Rex setup to run the offline suite.
4. Open a pull request against `main`. Explain what changed, why, and which
   checks you ran. Note any checks you could not run.

Keep real transcripts, credentials, local configuration, and generated packages
out of your changes. Contributions are covered by the project's [MIT license](../LICENSE).
