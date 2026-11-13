# Usage, privacy, and limits

[Project README](../README.md) · [Documentation](README.md) · [Setup](setup.md)

[Workflow](#annotate-a-reply) · [Keys](#key-reference) ·
[Insert or Send](#insert-versus-send) · [Privacy](#privacy-and-limits)

## Annotate a reply

1. Start your agent normally in a Rex pane after [setup](setup.md).
2. Press **Ctrl+S, then o** to open the reply picker.
3. Use `j`/`k` or `/` search, then **Enter** to open a reply. Newest replies are
   first. Rows show a compact relative time and preview, not internal IDs.
4. Select a quote with `v` or `V`, then **Enter** to write a comment. Without a
   selection, Enter uses the current logical line, including a hard newline
   when one exists.
5. Save the comment with **Ctrl+S**. Saved quotes and note labels are yellow;
   this is separate from the active Vim selection.
6. Preview with `p`, copy with `y`, insert with `s`, or Send with `S`.

The pane is centered and keeps the source pane's width. Its help header wraps
on narrow panes without changing the reply text or quote positions. Closing it
restores source focus only if you have not deliberately moved elsewhere.

## Key reference

| Where | Key | Action |
| --- | --- | --- |
| Reply picker | `j` / `k`, `/`, Enter | Move, search, and open a reply |
| Reply view | `hjkl`, `w` / `b`, `/` | Native Vim movement and search |
| Reply view | `v` / `V`, then Enter | Comment on characters / logical lines |
| Reply view | Enter without a selection | Comment on the current logical line |
| Comment editor | `Ctrl+S` | Save a multiline comment |
| Comment editor | Esc, then `q` | Cancel; confirm before discarding edits |
| Reply view | `m` | Edit or remove a saved note |
| Reply view | `p` | Preview the exact Markdown; `q` / Esc returns |
| Reply view | `y` | Copy the Markdown to the macOS clipboard; stay open |
| Reply view | `s` | Insert into the original agent draft; do not submit |
| Reply view | `S` | Send immediately to the original agent |
| Reply view | `q` | Close; warn before discarding unfinished notes |

## Insert versus Send

**Lowercase `s` never submits an extra Return. Uppercase `S` sends immediately.**
There is no typed `SEND` confirmation for uppercase S.

- **Pi:** insertion uses its editor API, including with Pi-vim. The existing
  draft is preserved.
- **Codex, Claude, and CUX:** insertion uses guarded bracketed paste. Keep the
  original agent at an editable prompt, not a dialog. Lowercase `s` asks you to
  confirm that prompt is ready before it pastes.
- **Both actions:** the annotation pane closes only after successful delivery.
  Errors keep your notes open. Do not automatically retry a failed operation.

Multiple notes form one Markdown payload. Preview, copy, insert, and Send use
the same formatter and selected quotes. Sending feedback may start an agent's
next model response; opening, selecting, and commenting do not send one.

## When delivery fails

1. Keep the annotation pane open so you do not lose the notes.
2. Inspect the original draft. A timeout can mean the paste or Send already
   happened; retrying blindly could duplicate it.
3. Read the error and [troubleshooting guide](setup.md#common-fixes). A changed
   process or conversation must not receive feedback intended for the old one.

The plugin does not select a different session or retry a side effect for you.

## Other terminal panes

An unrecognized terminal pane can be opened as an immutable terminal snapshot.
This path is **copy only**: it does not acquire an agent-reply binding or enable
insertion/Send. A terminal snapshot may contain any captured terminal text, not
only assistant replies. Older discarded scrollback cannot be recovered.

## Requirements

Use local macOS Rex with its CLI, Neovim with `vim.system` and `getregion`, and
Python 3.9+. Pi also needs its normal Node.js runtime and the registered bridge.
See [required tools](setup.md#required-tools) for installation details.

## Privacy and limits

- Annotation drafts, preview, and Neovim search history stay in memory. No swap,
  undo, shada, modelines, user Neovim config, or user plugins are loaded.
- Copy deliberately moves the payload to your clipboard. Insert/Send moves it
  to your agent, which may persist it under that agent's own history settings.
- Agent reply readers export assistant-visible text only. They exclude hidden
  reasoning, user messages, system instructions, tools, images, and extension state.
- Pi replies cap at **4 MiB and 5,000 replies**. Native transcript inputs cap at
  **4 MiB and 5,000 records before filtering**. Terminal snapshots cap at 4 MiB.
  Oversized input fails visibly instead of returning partial history.
- Native registrations store private IDs, paths, and process identity, not copied
  replies or feedback. Pi uses a private UID/PID-local Unix socket.
- Delivery rechecks the saved Rex pane, process, and conversation. It never
  targets whichever pane happens to have focus; unknown or changed targets fail.
- Force-closing a pane can discard its temporary notes without a warning.

**Next:** [Troubleshooting](setup.md#common-fixes) ·
[Exact-session details](../integrations/README.md) ·
[Related tools](related-tools.md)
