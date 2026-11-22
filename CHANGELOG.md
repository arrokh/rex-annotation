# Changelog

[Project README](README.md) · [Documentation](docs/README.md)

## 0.2.13

- Ask the Rex iPhone/iPad client to select the new Annotations tab after opening it. If the client cannot switch, the tab is still available manually.
- Send annotations to busy Pi sessions as a follow-up, without interrupting the active turn. Inserting into a draft still requires an idle editor.

## 0.2.12

- Open annotations in a dedicated tab on iPhone and iPad to avoid relying on floating-pane input focus. Mac still uses a floating pane.
- Add a physical O key binding alongside the existing `Command+Shift+O` binding. Physical iPad keyboard behavior has not yet been verified.

## 0.2.11

- Add `Command+Shift+O` as a direct shortcut to open annotations, including with a hardware keyboard on iPad. Keep `Ctrl+S`, then `o` available.

## 0.2.10

- Open the annotation pane at full Rex window width on iPhone and iPad. The Mac default remains half width.

## 0.2.9

- Allow Rex on iPhone and iPad to open annotations over Tailscale when the source pane runs on the same Mac as the Rex server. Clipboard copy is unavailable for these clients.

## 0.2.8

- Send the combined annotation draft directly from the reply picker with `Ctrl+Enter`.
- Open the annotation pane at 50% of the Rex window width, regardless of how narrow the source pane is.

## 0.2.7

- Manage notes across all replies with `m`, from the picker or any reply. `p` previews the combined feedback.
- Open the annotation pane at half the source pane’s width by default; the interface reflows when resized.

## 0.2.6

- Open a keyboard-navigable note list with `m`. Edit a selected note with Enter, or remove it with `x` and confirmation. Saving returns to the note list without closing the pane.

## 0.2.5

- Show **Last opened** on its own divider above the previously newest reply.
- Preview the combined draft with `p` and manage notes on the highlighted reply with `m` directly from the reply picker.
- Press `x` in reply detail to remove the newest note on the current line. Confirm with `x`, or cancel with `q` or `Esc`.

## 0.2.4

- Mark the previously newest reply as **Last opened** for each conversation. The marker stays fixed while navigating the open pane.
- Keep annotations across replies in one draft, and show note counts beside annotated replies in the picker.
- Press `Ctrl+Y` or `Ctrl+N` in reply detail to annotate the current line with `Yes` or `No` without opening the comment editor or sending feedback.

## 0.2.3

- Open long Claude sessions when the retained transcript starts with a tool result whose call was outside the read window.

## 0.2.2

- Render simple bold, inline code, and links in terminal reply detail, and align simple Markdown tables. Preserve the original Markdown when quoting or annotating.

## 0.2.1

- Style Markdown headings, list markers, quotations, and fenced code directly in terminal reply detail without changing the quoted text.

- Remove the experimental web preview, its localhost certificate setup, and the `Ctrl+S`, then `Shift+O` binding. The terminal annotator remains available.
- Save comments with `Enter` and add comment newlines with `Shift+Enter`. In reply detail and preview, use `Shift+Enter` to insert and `Ctrl+Enter` to send.

## 0.2.0

- Bundle an optional, sample-only Markdown review prototype for Rex Quick Look. Run `rex-annotation web-preview --trust-local-certificate` and Shift+Cmd-click the printed HTTPS link.
- Bind `Ctrl+S`, then `Shift+O` to Rex Quick Look for on-screen items. Lowercase `o` still opens the terminal annotator.
- Keep annotations open when Pi is busy and show a retry hint without a blocking Neovim prompt.

## 0.1.16

- Use `Ctrl+E` to edit, `Ctrl+W` to toggle wrapping, and `Ctrl+Enter` to save a comment. Use `n` and `N` to jump between notes; remove the bracket aliases.
- Shorten the Markdown payload to quote-and-feedback pairs while keeping multiline content.

## 0.1.15

- Jump between annotations with `n` and `N`. Repeat Vim searches with `\n` and `\N` in reply detail.
- Use muted sage, rose, and slate-blue highlights for Yes, No, and other comments.

## 0.1.14

- Show the exact selected quote in a scrollable, read-only preview when creating or editing a comment.
- Save `Yes` and `No` comments with `Ctrl+Y` and `Ctrl+N` without sending anything to the agent.
- Jump between saved annotations with `[a` and `]a`; use `\e` to edit the focused annotation directly.

## 0.1.13

- Fix Claude and CUX reply discovery when transcript rows carry different `sessionId` and `session_id` values. The canonical `sessionId` still has to match the bound conversation.

## 0.1.12

- Use Claude's persisted `last-prompt.leafUuid` to select a provable active branch, including opaque checkpoints; unresolved forks still fail closed.
- Add regression coverage for active-branch selection and stale-reply exclusion.

## 0.1.11

- Return from an opened reply to the reply list with Esc, restoring selection and picker options while confirming before discarding unfinished annotations.
- Toggle reply line wrapping with `\w` and show the current wrap mode in the statusline.
- Add regression coverage for back navigation, wrap toggling, and unfinished annotations.

## 0.1.10

- Read only the latest bounded window of native transcripts, so large session histories do not block recent reply annotations.
- Preserve Codex session identity and reject truncated Claude history unless its remaining graph still proves one unambiguous conversation.
- Add regression coverage for oversized transcripts, recent-record limits, and ambiguous truncated branches.

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
