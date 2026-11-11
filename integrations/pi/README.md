# Pi bridge for Rex Annotation

The [standalone project root](../../README.md) is the preferred Pi package:

```sh
pi install /absolute/path/to/rex-annotation
```

The subdirectory remains independently installable, but install only one of the
two paths to avoid loading the same bridge twice.

Existing Pi processes keep their loaded extension. A deliberate `/reload` or a
new process loads a changed bridge, but **either can clear a session-only auth
selection**. Do not reload on the user's behalf. Neovim-only UI changes need
only a new annotation pane, not a Pi reload.

## Operations

- `replies`: visible assistant text from `ctx.sessionManager.getBranch()`, in
  active-branch order. Neovim renders the list newest first with relative time
  and a message preview. No session-file guessing or viewport scraping.
- `insert`: append the exact annotation payload through `ctx.ui.setEditorText`,
  without submission and regardless of Pi-vim Normal/Insert mode. Existing
  draft text is preserved; the result is checked through `getEditorText`.
- `send`: explicitly send the annotation payload through `pi.sendUserMessage`.
  **Neovim uppercase S now sends immediately, without typing SEND.** It may
  start a model response. This path is never used by lowercase s or by capture.
- `snapshot` and `status`: bounded compatibility/read-only operations.

Inserts and sends require the original Rex session/block/PID, the same Pi
conversation, an idle agent, and no queued messages. Errors preserve the
annotation pane and draft. Never retry a timeout without checking the source:
the operation might already have happened.

## Privacy and lifecycle

The event-driven socket is `/tmp/rex-annotate-pi-<uid>/<pid>.sock`; its directory
is private (`0700`) and the socket is `0600`. There is no TCP listener, polling,
transcript-copy file, annotation handoff file, or automatic agent message.

The reply list exports text blocks only. It excludes user messages, hidden
thinking, tool calls/results, system instructions, extension state, and images.
Real code/table pipes and multiline text are preserved. Lists over 4 MiB or
5,000 replies fail visibly instead of truncating. Requests and responses are
bounded in size/time; Neovim waits at most three seconds for the socket.

The bridge closes on normal Pi shutdown/reload. Force-kill can leave a stale
socket inode, but no transcript payload file. Do not remove a live process's
socket. Old/missing bridges produce an actionable error rather than falling
back to an unrelated session.

## Tests

From the project root:

```sh
node --test integrations/pi/test/*.test.mjs
```

See the root README for disposable, network-denied actual Pi/Pi-vim checks.
No production agent message is sent by those tests.
