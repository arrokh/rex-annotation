# Usage, privacy, and limits

[Project README](../README.md) · [Documentation](README.md) · [Setup](setup.md)

[Workflow](#annotate-a-reply) · [Keys](#key-reference) ·
[Insert or Send](#insert-versus-send) · [Privacy](#privacy-and-limits)

## Annotate a reply

1. Start your agent normally in a Rex pane after [setup](setup.md).
2. In the pane with the reply, press **Ctrl+S, then o** (two steps, not a
   single chord). You can also use the Rex palette action **Annotate Agent
   Reply or Terminal Output**.
3. Use `j`/`k` or `/` search, then **Enter** to open a reply. Newest replies are
   first. Rows show a compact relative time and preview, not internal IDs. Press
   **Esc** in a reply to return to the list without losing saved notes.
   The **Last opened** divider sits just above the reply that was newest the
   previous time you opened this conversation’s picker. It is not selectable.
   The marker stays put when you go back from a reply. It only updates when
   you open a new annotation pane, and is hidden if that reply is unavailable.
4. Select a quote with `v` or `V`, then **Enter** to write a comment. Without a
   selection, Enter uses the current logical line, including a hard newline
   when one exists.
5. The comment editor shows the exact quote above the editable text. Save with
   **Enter** (`Shift+Enter` adds a newline), or use **Ctrl+Y** / **Ctrl+N** to save `Yes` / `No` without
   typing. These only save a note; they do not send it. Saved quotes and note
   labels use muted sage for `Yes`, rose for `No`, and slate blue for other
   comments. Vim’s active selection keeps its own highlight.
6. Preview with `p`, copy with `y`, insert with `Shift+Enter`, or Send with `Ctrl+Enter`.

Reply detail styles Markdown headings, lists, quotes, fenced code, simple inline formatting, and pipe tables. In Normal mode, supported inline delimiters and link destinations are hidden for reading. Visual mode reveals them on the active line; annotations still quote the original Markdown.

On Mac, the pane opens centered at half the Rex window’s width, like one pane in an
even side-by-side split, regardless of the source pane’s width. Resize or
maximize it in Rex and the UI adjusts to the available space. On iPhone and
iPad, the pane opens at the full Rex window width by default. The help header wraps
without changing the reply text or quote positions. Closing it
restores source focus only if you have not deliberately moved elsewhere.

## What feedback looks like

For example, select a line in an agent’s plan and add a comment. Press `p`
to review the Markdown before inserting it:

```markdown
# Terminal annotations

> Drop the old table after the migration.

Feedback: Keep it until the backfill is verified.
```

To add more feedback, select another quote or press **Esc** to choose a
different reply. Saved notes stay in the pane. The picker shows `[1 note]` or
`[2 notes]` beside replies with saved notes. Preview, copy, insert, and Send
use the combined draft. When there are notes on multiple replies, the draft
groups them newest first; reply numbers refer to positions in the picker (the
newest reply is 1). Closing the pane warns about feedback that has not been copied or delivered.

## Manage notes

Press `m` in the picker or in any reply to see all notes in this pane, grouped
by reply in newest-first order. `p` previews the same combined feedback.
Move with `j` / `k` and press **Enter** to edit. The original quote stays
visible and cannot be edited. Save with **Enter** to return to the note list
without losing your place. Press `x`, then `x` to remove the selected note;
`q` or Esc cancels the confirmation. Outside confirmation, `q` or Esc returns
to the screen you opened the note list from.

## Key reference

| Where | Key | Action |
| --- | --- | --- |
| Reply picker | `j` / `k`, `/`, Enter | Move, search, and open a reply |
| Reply picker | `p` | Preview the combined draft; `q` / Esc returns to the picker |
| Reply picker | `Ctrl+Enter` | Send the combined draft immediately if there are annotations |
| Reply picker | `m` | Open the note list across all replies |
| Reply view | `hjkl`, `w` / `b`, `/` | Native Vim movement and search |
| Reply view | `Ctrl+W` | Toggle line wrapping on/off |
| Reply view | `Esc` | Return to the reply list and keep saved notes |
| Reply view | `v` / `V`, then Enter | Comment on characters / logical lines |
| Reply view | Enter without a selection | Comment on the current logical line |
| Reply view (Normal mode) | `Ctrl+Y` / `Ctrl+N` | Save `Yes` / `No` on the current logical line without opening the editor or sending |
| Comment editor | `Enter` / `Shift+Enter` | Save comment / add a newline in Insert mode |
| Comment editor | `Ctrl+Y` / `Ctrl+N` | Save `Yes` / `No` in place of the editor text |
| Comment editor | `PgUp` / `PgDn` | Scroll the read-only quote |
| Comment editor | Esc, then `q` | Cancel; confirm before discarding edits |
| Reply view | `n` / `N` | Jump to the next / previous annotation; wraps at the ends |
| Reply view | `\n` / `\N` | Repeat the last Vim search in the same / opposite direction |
| Reply view | `Ctrl+E` | Edit the annotation you jumped to or the one under the cursor |
| Reply view (Normal mode) | `x`, then `x` | Remove the newest annotation on the current logical line. Press `q` or Esc to cancel |
| Reply view | `m` | Open the note list across all replies |
| Note list | `j` / `k`, `Enter`, `x`, `q` / Esc | Move, edit, request removal, or go back |
| Reply view | `p` | Preview the exact Markdown; `q` / Esc returns |
| Reply view | `y` | Copy the Markdown to the macOS clipboard; stay open |
| Reply view and preview | `Shift+Enter` | Insert into the original agent draft; do not submit |
| Reply view and preview | `Ctrl+Enter` | Send immediately to the original agent |
| Reply view | `q` | Close; warn before discarding unfinished notes |

## Insert versus Send

**Shift+Enter inserts without submitting. Ctrl+Enter sends immediately.**
There is no typed `SEND` confirmation.

- **Pi:** insertion uses its editor API, including with Pi-vim. The existing
  draft is preserved.
- **Codex, Claude, and CUX:** insertion uses guarded bracketed paste. Keep the
  original agent at an editable prompt, not a dialog. `Shift+Enter` asks you to
  confirm that prompt is ready before it pastes.
- **Both actions:** the annotation pane closes only after successful delivery.
  Errors keep your notes open. Do not automatically retry a failed operation.

Multiple notes form one compact Markdown payload. Each block quote is followed
by its `Feedback:`. Preview, copy, insert, and Send use the same formatter. Sending feedback may start an agent's
next model response; opening, selecting, and commenting do not send one.

## When delivery fails

1. Keep the annotation pane open so you do not lose the notes.
2. Inspect the original draft. A timeout can mean the paste or Send already
   happened; retrying blindly could duplicate it.
3. Read the error and [troubleshooting guide](setup.md#common-fixes). A changed
   process or conversation must not receive feedback intended for the old one.

The plugin does not select a different session or retry a side effect for you.

## Other terminal panes

In a regular shell pane, use the same shortcut to annotate a read-only snapshot
of the terminal text. Select and comment as usual, then press `y` to copy the
notes. This path is **copy only**: there is no bound agent to receive the text.
A snapshot may include any captured terminal text, not just assistant replies.
Older discarded scrollback cannot be recovered.

## Requirements

The Mac running the source pane needs Rex and its CLI, Neovim with `vim.system`
and `getregion`, and Python 3.9+. Pi also needs its normal Node.js runtime and
registered bridge. You can open Annotate from Rex on that Mac or from Rex on
an iPhone or iPad connected to that Mac through Tailscale. Clipboard copy (`y`)
is unavailable when opening from iPhone or iPad; Preview, Insert, and Send
remain available for supported agents. A plain terminal snapshot cannot send.
See [required tools](setup.md#required-tools) for installation details.

## Privacy and limits

- Annotation drafts, preview, and Neovim search history stay in memory. No swap,
  undo, shada, modelines, user Neovim config, or user plugins are loaded.
- Copy deliberately moves the payload to your clipboard. Insert/Send moves it
  to your agent, which may persist it under that agent's own history settings.
- Agent reply readers export assistant-visible text only. They exclude hidden
  reasoning, user messages, system instructions, tools, images, and extension state.
- Pi replies cap at **4 MiB and 5,000 replies**. Native readers load at most the
  latest **4 MiB and 5,000 transcript records** (plus Codex session metadata);
  older history is skipped. Oversized individual records fail visibly. Terminal
  snapshots cap at 4 MiB.
- Native registrations store private IDs, paths, and process identity, not copied
  replies or feedback. Pi uses a private UID/PID-local Unix socket.
- The **Last opened** marker persists locally under
  `$XDG_STATE_HOME/rex-annotation/last-opened` (default: `~/.local/state`).
  It stores only hashed conversation and reply identifiers, not text or notes.
- Delivery rechecks the saved Rex pane, process, and conversation. It never
  targets whichever pane happens to have focus; unknown or changed targets fail.
- Force-closing a pane can discard its temporary notes without a warning.

**Next:** [Troubleshooting](setup.md#common-fixes) ·
[Exact-session details](../integrations/README.md) ·
[Related tools](related-tools.md)
