# Changelog

[Project README](README.md) · [Documentation](docs/README.md)

## 0.1.9

- Reorganize the README and guides around setup, use, troubleshooting, and development; add a documentation index, per-agent navigation, and references to Herdr Annotate, Plannotator, and Plannotator TUI.
- Check documentation links, heading targets, and routes back to the index with offline tests.

## 0.1.8

- Fix Claude/CUX reply loading after parallel tool calls: distinguish streamed response blocks and matched tool results from genuine conversation forks.
- Validate logical graph continuity through progress, attachments and explicit compaction links; keep genuine forks, malformed identities and cycles fail-closed.
- Validate all tool-result IDs in mixed text/image context records, including parallel tool results, without exporting private context.
- Add regressions based on the actual failing graph shape and cover it in Claude/CUX picker, insert and Send smoke tests.

## 0.1.7

- Recover Codex's deferred startup binding from the single rollout open by the exact Rex foreground PID, so resumed sessions work before a new prompt.
- Reject missing, ambiguous, replaced, or non-foreground rollout files; never choose by recency.
- Add no-input native startup coverage for Codex's deferred lifecycle hooks.

## 0.1.6

- Make plain installation detect and configure Pi, Codex, and Claude/CUX automatically, with no extra setup flags.
- Enable and persist approval for only Rex Annotation's exact Codex hooks through Codex's native config API; verify trust without a manual `/hooks` step.
- Activate and verify running Rex config automatically; leave existing coding-agent processes and authentication untouched.
- Verify selected CLIs and Pi registration, and report hook-policy blockers instead of claiming setup succeeded.

## 0.1.5

- Show complete multiline startup errors safely instead of crashing the annotation error screen.
- Remove obsolete old-tap migration guidance and keep GitHub release titles version-only.

## 0.1.4

- Give saved annotation spans and note labels a dedicated high-contrast yellow highlight, distinct from active text selection.

## 0.1.3

- Treat CUX as Claude for setup, diagnostics, foreground delivery and child-restart-safe transcript binding.
- Keep every detail-view shortcut visible in a compact, width-aware multiline header that reflows on resize without changing reply text.

## 0.1.2

- Automatically bind normal `codex` and `claude` launches inside Rex through native lifecycle hooks; no wrapper or CLI replacement is required.
- Install Claude user hooks idempotently and diagnose their actual registration rather than only plugin packaging.
- Maintain the Homebrew formula in this repository; add explicit custom-tap installation and legacy-tap migration steps.

## 0.1.1

- Use native macOS libproc for process identity; no setuid ps execution in sandboxed hooks.
- Bind new Codex/Claude sessions before their first transcript is persisted, without weakening delivery validation.
- Add a real native startup smoke test and explicit Neovim/Python/Rex prerequisites.

## 0.1.0

Initial public release.

- Neovim reply picker for Pi, Codex CLI, and Claude Code in Rex.
- Compact aligned reply timestamps, Enter comments, and persistent quote highlights.
- Non-submitting `s` and immediate `S`; successful delivery closes the overlay.
- Exact-session integration, bounded transcript reads, and private metadata-only bindings.
- Homebrew packaging, detected-agent setup, and read-only status/doctor.
- MIT license.
