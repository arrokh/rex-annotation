# Changelog

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
