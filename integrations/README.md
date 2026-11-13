# Agent integrations and exact native sessions

[Project README](../README.md) · [Documentation](../docs/README.md) ·
[Setup](../docs/setup.md) · [Usage](../docs/usage.md)

## Choose an agent

| Agent | Start with | How replies are read |
| --- | --- | --- |
| Pi | [Pi guide](pi/README.md) | Live active-branch/editor bridge |
| Codex CLI | [Codex guide](codex/README.md) | Exact foreground process and registered native rollout |
| Claude Code / CUX | [Claude/CUX guide](claude/README.md) | Exact hook transcript; CUX also binds the native child lifetime |

For everyday use, start with those guides. The rest of this page is the shared
native-session safety and developer reference. CUX uses the Claude adapter;
it is not a separate fourth integration.

[Activation](#activate) · [Binding](#automatic-rex-binding) ·
[Adapter protocol](#internal-cli-contract) ·
[Limits](#privacy-limits-and-format-caveats) · [Evidence](#evidence-and-tests)

`session_replies.py` reads only the transcript registered for the saved Rex
session/block and foreground PID/start identity. It never selects the newest
session file or copies a transcript into plugin storage.

## Activate

After installing the CLI, plain `rex-annotation install` configures detected
agents. The scoped source-checkout examples below are optional; ordinary
`codex`, `claude`, and `cux` commands inside Rex need no annotation wrapper.

### Codex CLI

From this checkout:

```sh
python3 scripts/install.py --codex
codex
```

The installer links `~/.agents/skills/rex-annotation` and merges the bundled
lifecycle hooks into `$CODEX_HOME/hooks.json` (normally `~/.codex/hooks.json`).
Plain `rex-annotation install` detects Codex automatically; `--codex` is only a
scoped selection. Setup enables the hooks feature and approves only the exact
installed Rex Annotation hook definitions, without another flag or prompt.
It uses Codex's `hooks/list` keys/current hashes and `config/batchWrite` trust
persistence, then verifies the hooks are enabled and trusted. The config-only
app-server is isolated, bounded, and network-denied; it never starts a coding-agent thread.
Unrelated hooks, explicit disables, authentication, and sandbox/tool-approval
policy remain intact. Unsupported protocol or policy blockers fail visibly;
no hook-trust bypass flag or guessed approval hash is used.

The trusted hooks register the exact hook-provided `session_id` and
`transcript_path` at SessionStart and UserPromptSubmit, refresh at Stop, and
remove the matching registration at SessionEnd. Codex may defer those events
until the first prompt. Before that prompt, Rex Annotation can recover a missing
binding only when the exact foreground Codex PID has exactly one canonical
rollout file open. It verifies the thread ID and transcript contents before
recording metadata. Missing or multiple candidates fail closed; it never scans
for or selects the newest rollout. A new session invalidates its old binding
even if the new session has no persistent transcript.

The installed `$rex-annotation` skill is an executable fallback. It uses
`CODEX_THREAD_ID` from Codex's tool shell and matches only canonical rollout
filenames for that UUID. Multiple matching rollouts fail rather than choosing
the latest. Re-run the skill after any conversation switch if native hooks are
not enabled; validators cannot observe an unregistered in-memory switch.
Use the native hooks for automatic current-session tracking.

### Claude Code

Install once, then use the normal command in a Rex pane:

```sh
python3 scripts/install.py --claude
claude
```

The installer merges owned lifecycle handlers into
`${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`. Other hooks, settings,
authentication, and permission policy remain unchanged. Run setup under the same
configuration-directory override as Claude. A user or organization that disables
hooks keeps that policy; setup does not turn it off.

The root plugin remains available for optional explicit launchers. If loading it
manually, use **the whole repository root**; `integrations/claude` alone is not a
standalone plugin.

Claude's SessionStart/UserPromptSubmit hooks register its exact
`session_id`/`transcript_path`; Stop refreshes metadata and SessionEnd removes
the matching binding. Subagent events are ignored.

### Claude through CUX

Run `cux` or `cux run` normally after plain `rex-annotation install`. CUX
is a Claude launcher, not a fourth agent. Detection works with CUX alone on PATH.
The foreground CUX PTY wrapper owns delivery; the native Claude child's PID/start
identity owns transcript validity. Child exit makes the old binding unusable, and
a resumed child registers again even when its conversation id stays the same.
A delayed old child's SessionEnd cannot remove the resumed child's binding.

Use the same `CLAUDE_CONFIG_DIR` at setup that CUX/Claude uses. Account enrollment,
credentials, refresh and switching remain entirely under CUX control. Tests use a
synthetic PTY supervisor and child restart; no real CUX accounts are accessed.

### Automatic Rex binding

Ordinary `codex` and `claude` commands inherit `REX_SESSION` and `REX_BLOCK` from
Rex. Hooks query that exact pane's foreground process and verify it belongs to
the hook's ancestor chain before registering the supplied conversation and
transcript. They never choose a transcript by modification time, bind whichever
pane has focus, or shadow the native CLI. Hooks outside Rex are no-ops.
Background processes and subagent events cannot replace a foreground binding.
Codex shared-daemon or remote-server sessions whose hooks run outside that local
process ancestry fail closed. Use `codex --no-daemon` for those sessions; setup
does not change your daemon preferences or attach to an unrelated daemon.

Optional `rex-annotation codex` / `rex-annotation claude` launchers remain
supported. They use `exec` and provide an explicit `REX_PID`/`REX_ANNOTATION_ROOT`;
normal commands no longer require those variables. No provider, model, key,
authentication, or approval settings are changed.

Existing processes are not restarted, reloaded, or registered by installation.
Start a new process deliberately after setup.

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
- Claude streams one assistant record per content block. Parallel tool results
  can point to their own tool-call records, so sibling UUID links alone are not
  a conversation fork. The adapter checks shared API response IDs, exact
  tool-use/result IDs, writer identity, and parent links before validating one
  logical conversation chain. Mixed tool-result/context records validate every
  result ID too. Progress, attachments, and explicit compaction links preserve
  graph continuity without exporting their content. Opaque metadata leaves alone
  are not conversation forks. Genuine forks, duplicate or
  unresolved identities, and cycles still fail closed; no newest-leaf or
  timestamp guess is used.
- Multiple Codex rollback/fork files and rollouts with a `thread_rolled_back`
  event fail closed; undone replies are not exported as current history. These
  adapters do not claim Pi's in-memory active-branch API. Native transcript
  formats are local implementation details and may require updates.
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

Native startup checks have been exercised with Codex CLI 0.167.1 and Claude
Code 2.1.322. These are tested versions, not a guarantee for future transcript
formats. Format and lifecycle references:

- [Codex hooks, locations, trust, lifecycle payloads](https://learn.chatgpt.com/docs/hooks)
- [Codex plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Claude hooks](https://code.claude.com/docs/en/hooks.md)
- [Claude plugin layout](https://code.claude.com/docs/en/plugins/create.md)
- [Claude session management](https://code.claude.com/docs/en/sessions.md)
- [Anthropic SDK transcript reconstruction and parallel-tool handling](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/sessions.py)

`npm test` runs synthetic adapter/hook/skill/lifecycle tests. Optional
`python3 scripts/test-native-overlays.py` compiles two tiny fake executables and
runs Codex/Claude automatic hook binding → picker → Enter comment → s/S flows in
disposable Rex sessions without `REX_PID`, `REX_ANNOTATION_ROOT`, or wrappers.
It verifies exact UTF-8 paste, no Return for s, exactly one Return for S,
auto-close, source focus, and owned-session cleanup. Claude/CUX fixtures include
streamed parallel tools, mixed tool-result/context records, and opaque progress
links, not only a linear chat.
`--agent claude` or `--agent cux` runs a focused check. It never invokes a real
coding agent or sends a model request.

`python3 scripts/test-native-startup.py --agent claude` checks real Claude
SessionStart registration from the ordinary `claude` command after installing
user hooks in a disposable network-denied home. `--launcher` checks the optional
explicit launcher instead. New sessions
can register a pending transcript path without creating that file. The smoke
seeds only its owned test transcript when needed; no model prompt is submitted.
Read operations return no replies until persistence; delivery still requires an
actual matching transcript. macOS process identity uses libproc with owner/PID
and microsecond-start checks, not setuid `ps`.

The equivalent Codex check verifies automatic installer trust and ordinary
native binding, including a resumed synthetic session that is recovered before
any new prompt. A separate fresh-start path submits only offline fixture input
to an unreachable fixture model, with all networking denied and no real
credentials. Neither path can send a real model request. An unexpected
hook-review screen fails the smoke test. Temporary Rex sessions/homes are
deleted on both success and failure.

**Next:** [Test command guide](../docs/development.md#optional-live-checks) ·
[Troubleshooting](../docs/setup.md#common-fixes) ·
[Related annotation projects](../docs/related-tools.md)
