# Exact native-agent sessions

`session_replies.py` reads only the transcript registered for the saved Rex
session/block and foreground PID/start identity. It never selects the newest
session file or copies a transcript into plugin storage.

## Activate

### Codex CLI

From this checkout:

```sh
python3 scripts/install.py --codex
bin/rex-annotation codex
```

The installer links `~/.agents/skills/rex-annotation` and merges the bundled
lifecycle hooks into `$CODEX_HOME/hooks.json` (normally `~/.codex/hooks.json`).
Unrelated hooks remain intact. **Review and trust the new local hooks yourself
in Codex's `/hooks` screen.** The installer never bypasses hook trust, changes
approval policy, or starts an agent.

The trusted hooks register the exact hook-provided `session_id` and
`transcript_path` at SessionStart and UserPromptSubmit, refresh at Stop, and
remove the matching registration at SessionEnd. A new session invalidates its
old binding even if the new session has no persistent transcript.

The installed `$rex-annotation` skill is an executable fallback. It uses
`CODEX_THREAD_ID` from Codex's tool shell and matches only canonical rollout
filenames for that UUID. Multiple matching rollouts fail rather than choosing
the latest. Re-run the skill after any conversation switch if native hooks are
not enabled; validators cannot observe an unregistered in-memory switch.
Use the native hooks for automatic current-session tracking.

### Claude Code

In the source Rex pane:

```sh
bin/rex-annotation claude
```

The launcher loads **the whole repository root** as a local Claude plugin;
`integrations/claude` alone is not a standalone plugin. The root manifest and
hooks keep the shared Python adapter inside the plugin when the project moves
or is packaged. No global Claude configuration or auth is changed.

Claude's SessionStart/UserPromptSubmit hooks register its exact
`session_id`/`transcript_path`; Stop refreshes metadata and SessionEnd removes
the matching binding. Subagent events are ignored.

### Launcher environment

`bin/rex-annotation` uses `exec`, preserving the native CLI's PID. It sets
`REX_ANNOTATION_ROOT` to the checkout and `REX_PID` to that PID. Rex supplies
`REX_SESSION` and `REX_BLOCK`. No provider, model, key, authentication, or
approval settings are changed. Normal agents outside this opt-in launcher have
no registration and the global hooks are no-ops for them.

Existing processes are not restarted, reloaded, or registered by installation.
Start a new process deliberately, or use an explicitly prepared binding.

## Internal CLI contract

```sh
python3 integrations/session_replies.py replies --agent codex --pid PID --session REX_SESSION --block REX_BLOCK
python3 integrations/session_replies.py validate --agent codex --pid PID --session REX_SESSION --block REX_BLOCK --conversation ID
```

Use `--agent claude` for Claude Code. Replies are **oldest first**; Lua reverses
them for the newest-first picker. Success is JSON:

```json
{"sessionId":"conversation-id","replies":[{"id":"internal-id","timestamp":"2026-01-02T03:04:05Z","text":"Visible reply"}]}
```

`validate` exits successfully only if agent/PID/start/Rex/conversation/transcript
still match. The Lua layer runs it before delivery and again between paste and
Return for Send. Errors go to stderr and keep annotations open. IDs remain
internal and never appear in picker rows.

Hooks use `register` with the same scope plus `--conversation ID --transcript
ABSOLUTE_JSONL_PATH`. `unregister` additionally requires the exact conversation,
so a delayed old SessionEnd cannot remove a newer session's binding.

## Privacy, limits, and format caveats

- Private metadata lives under `$XDG_STATE_HOME/rex-annotation/reply-bindings`
  (normally `~/.local/state/rex-annotation/reply-bindings`): directories `0700`,
  records `0600`, atomic replacement. `REX_ANNOTATION_STATE_DIR` overrides the
  state base for tests. Records contain IDs, transcript paths and process-start
  identity, never transcript or annotation text.
- Native input is bounded to **4 MiB and 5,000 JSONL records before filtering**.
  Malformed, stale, oversized, mismatched and control-bearing input fails visibly.
- Only known assistant-visible blocks are read: Claude `text`, Codex
  `output_text`/`refusal` on visible channels. Hidden analysis/thinking, tools,
  user messages, images, sidechains, summaries and unknown channels are excluded.
  Empty replies are skipped; terminal escapes are stripped.
- Ambiguous Claude parent graphs, multiple Codex rollback/fork files, and Codex
  rollouts with a `thread_rolled_back` event fail closed; undone replies are not
  exported as current history. These adapters do not claim Pi's in-memory active-branch API. Native
  transcript formats are local implementation details and may require updates.
- Claude transcripts can lag its in-memory conversation. A reply not yet flushed
  to disk may not appear until a later read. Hooks do not copy Stop's response
  text to work around that lag.
- Generic terminal paste cannot prove input readiness or rule out process races.
  Keep the source at its editable prompt. After an ambiguous error, inspect the
  source before retrying; the plugin does not retry side effects.

Normal SessionEnd removes its exact owned record. Force-kill may leave private
metadata; it cannot match a new process with a different start identity. If
removing metadata by hand, remove only a record whose PID/start and Rex scope
you own. Keep all native transcript files and other users' live bindings intact.

## Evidence and tests

Research used installed Codex CLI 0.167.0 and Claude Code 2.1.322, their current
primary docs, and native rollout schemas:

- [Codex hooks, locations, trust, lifecycle payloads](https://learn.chatgpt.com/docs/hooks)
- [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Claude hooks](https://code.claude.com/docs/en/hooks.md)
- [Claude plugin layout](https://code.claude.com/docs/en/plugins/create.md)
- [Claude session management](https://code.claude.com/docs/en/sessions.md)

`npm test` runs synthetic adapter/hook/skill/lifecycle tests. Optional
`python3 scripts/test-native-overlays.py` compiles two tiny fake executables and
runs Codex/Claude picker → Enter comment → s/S flows in disposable Rex sessions.
It verifies exact UTF-8 paste, no Return for s, exactly one Return for S,
auto-close, source focus, and owned-session cleanup. It never invokes a real
coding agent or sends a model request.

An additional native-startup check reached Codex's expected hook-trust screen
without approving it. Claude reached its editable prompt, but the restrictive
test sandbox denied the hook's `ps` process-identity query, so real Claude
startup registration remains unverified by that check. Neither check sent a
prompt, and both disposable Rex sessions were deleted and verified absent.
