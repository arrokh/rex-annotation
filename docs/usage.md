# Usage, privacy, and limits

## Annotate a reply

1. In an agent pane, press **Ctrl+S, then o**.
2. Pick a reply with `j`/`k`, `/` search, and **Enter**. The list is newest first;
   each row uses a fixed-width compact time column (`2m`, `3h`, `7d`) and an
   aligned message preview, never internal IDs.
3. Select a quote with `v` or `V`, then press **Enter** to write a comment.
4. Save the comment with **Ctrl+S**. The source span and note label stay highlighted
   in bold yellow with dark text, distinct from your active Vim selection.
5. Press **s** to insert without submitting, or **S** to send immediately.
   Both close the annotation pane **only after successful delivery**.

**Uppercase S submits immediately. There is no typed SEND confirmation.**
Lowercase `s` never sends an extra Return. Pi inserts through its editor API;
Codex/Claude use guarded bracketed paste and still ask whether the input is ready
for an insertion. Put these agents at an editable prompt, not a dialog.

| Key | Action |
| --- | --- |
| `hjkl`, `w`/`b`, `/` | Native Vim movement and search |
| `v` / `V`, then Enter | Comment on selected characters / logical lines |
| `Ctrl+S` in a comment | Save a multiline comment |
| `Esc`, then `q` in a comment | Cancel; confirm before discarding edits |
| `m` | Edit or remove a saved note |
| `p` | Optional exact Markdown preview; `q` / Esc returns |
| `y` | Copy the same Markdown to the macOS clipboard; stay open |
| `s` | Insert into the original agent draft, then close; no submission |
| `S` | Send to the original agent immediately, then close |
| `q` | Close; warn before discarding unfinished notes |

Multiple notes share one Markdown payload. Delivery failures keep the notes open.
Preview, copy, insertion, and Send use the same formatter.

## Requirements

- Local macOS Rex and its `rex` CLI (API revision 11 tested).
- Neovim with `vim.system` and `getregion` (0.12.5 tested).
- Python 3.9+ for setup and native session adapters; Node.js/Pi for the Pi bridge.
- Native agent integrations below for exact reply history. Ordinary unrecognized
  terminal panes can still annotate an immutable terminal snapshot (copy only).

The annotation pane is centered and retains the source pane's width, including
split and zoomed layouts. Detail-view shortcuts stay in a separate multiline
header that reflows as the pane narrows; reply text and quote coordinates are
unchanged. Closing it restores the original source focus unless
you deliberately moved to another pane/window.


## Privacy and limits

- Quotes, comments, preview, and Neovim search history stay in memory. No swap,
  undo, shada, modelines, user Neovim config, or user plugins are loaded.
- Reply history is assistant-visible text only. Hidden reasoning, user messages,
  system instructions, tool data, images, and extension state are not exported.
- Pi replies are bounded to 4 MiB and 5,000 replies; native transcript inputs
  are bounded to 4 MiB and 5,000 records before filtering. Oversized input fails
  visibly rather than returning partial history. Ordinary terminal snapshots cap
  at 4 MiB; discarded terminal scrollback cannot be recovered.
- Native transcript registrations hold private metadata only, not copied replies
  or annotation payloads. The Pi bridge uses a UID/PID-local Unix socket.
- Every delivery targets the saved Rex session/block/process, never whichever
  pane happens to have focus. Unknown/changed targets are refused.
- An ambiguous timeout may mean insertion/submission already happened. **Inspect
  the original prompt before retrying.** Side effects are never retried for you.
- Copy intentionally changes the system clipboard. Force-closing an annotation
  pane can discard its temporary notes without a warning.


See [agent activation](../integrations/README.md) and [setup diagnostics](setup.md).
