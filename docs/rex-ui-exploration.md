# Rex-native UI exploration

[Documentation](README.md) · [Development](development.md)

## What is available

| Surface | Evidence | Fit for Rex Annotation |
| --- | --- | --- |
| Native palette | [`rex.ui.pick` and `rex.ui.input`](https://www.superlogical.com/rex/docs/customize/custom-ui) provide a filterable list and single-line input. Prompts require control API 17. | Good for choosing an action or a reply, but not for reading, selecting exact spans, or composing multiline feedback. |
| Floating panes | [Server API](https://www.superlogical.com/rex/docs/reference/api) documents `session.new_layer`, `session.resize_layer`, and `session.set_block_label`. The local server exposes all three. | Keep Rex as the outer shell. An optional wider review view would help when the source pane is narrow. |
| Native chrome | [Mac Settings](https://www.superlogical.com/rex/docs/reference/mac-settings) documents pane density, header visibility, and matching outer padding/header colors to a full-screen program. | Test the existing overlay against these settings before adding custom chrome. Don't change global settings on install. |
| Program status | [OSC 7501](https://www.superlogical.com/rex/docs/build/program-status) feeds terminal/tab and session-picker status. | Optional. Try it only if background progress proves useful. Never include reply text or comments, and don't mark ordinary editing as permission-blocked. |
| Key modes and events | [Key Modes](https://www.superlogical.com/rex/docs/customize/key-modes), [Lua Events](https://www.superlogical.com/rex/docs/automate/lua-events). | No need for global or exclusive modes: the editor already scopes keys to its buffers. Prefer explicit actions to a persistent watcher unless automatic updates justify one. |

The public API I reviewed documents palette prompts, not an embeddable arbitrary view or a multiline range editor. Rex already owns the action, placement, and focus; Neovim owns exact Unicode selection, multiline feedback, preview, and draft state. That seam is worth keeping.

## Compatibility on this Mac

Observed 2026-11-21:

- `Rex Beta.app` is build **2061**, the newest item in its configured [macOS ARM64 Preview appcast](https://blob.superlogical.com/public/rex-app/preview-arm64/appcast.xml) at the time of inspection. Its bundled Rex is `0.1.0-preview.21` (control API 18), and its bundled CLI exposes `rex.ui.pick` in Lua.
- `rex` on PATH and the **running server** report control API **11**; that CLI has no `rex.ui`. A newer bundled CLI is not proof that the current server can deliver prompts. I did not restart the server or open a live palette prompt.
- The appcast establishes build availability. Detailed release notes are available through the [Rex Beta Community MCP](https://www.superlogical.com/rex/docs/beta/community-mcp), which requires Discord membership and OAuth. No authenticated changelog was accessed.

## Recommended first prototype: focused review pane

Keep the existing picker and shortcuts. Use a Rex floating layer for a wider, centered review pane on demand; leave the current footprint as the default. Give the pane a human-readable title, use a short contextual toolbar (`Enter Note`, `Ctrl+E Edit`, `n/N Jump`, `p Preview`), and move less-used keys to a help view. Replace the raw pane ID in the visible statusline with reply position, note count, and wrap state. Keep Insert and Send visually and behaviorally distinct.

Test in synthetic Rex sessions at narrow and wide sizes, in light and dark, and after changing focus deliberately. Verify resize does not move the source pane or redirect delivery. Today duplicate-overlay detection depends on a block label containing the source ID; decouple that guard from the display title before making the title cosmetic. Continue to bind delivery to the original pane, process, and conversation. No overlay focus should determine the destination.

## Browser prototype: list and detail

Open [`rex/web-prototype/index.html`](../rex/web-prototype/index.html) in a browser, or run `open rex/web-prototype/index.html` from the repo root on macOS. Use the bottom switcher to compare Split, Stack, and Reader. Reply detail always shows formatted Markdown. Drag over the rendered text, or use `v` for characters and `V` for whole rendered blocks; then press Enter to annotate. Quotes contain visible text, not Markdown delimiters. The renderer supports a subset of Markdown and displays raw HTML as text. The prototype uses synthetic replies, keeps notes in memory, and simulates Insert/Send.

With this checkout loaded in Rex, **Ctrl+S, o** still opens the terminal annotator. **Ctrl+S, Shift+O** invokes the Mac client's documented [Quick Look](https://www.superlogical.com/rex/docs/reference/mac-actions#action-client-quick-look) action (also available via the default `Cmd+Y`). In the Mac app, `Shift+Cmd`-click on an on-screen link opens an in-app web preview, as observed by the user; `Cmd`-click opens the external browser. To try the fixture, serve it on loopback and use the visible URL `http://127.0.0.1:8847/`. The action takes no URL argument, so this binding cannot open a hardcoded prototype URL from an arbitrary pane. On Mac build 2061, the user tested two explicit terminal hyperlinks with Shift+Cmd-click: `https://example.com/` opened inside Rex, while `http://localhost:8847/` did not. A public plain HTTP control (`http://neverssl.com/`) also opened Chrome, while `https://localhost:8848/` with a trusted local certificate opened the prototype inside Rex. On this build, use trusted loopback HTTPS for the prototype, not a public tunnel. The keyboard action is still an experiment: it accepts no URL, and key delivery inside Quick Look has not yet been verified.

Neither the connected Mac client's `rex -C … actions`, the running server's `rex api list`, nor the public [Mac action reference](https://www.superlogical.com/rex/docs/reference/mac-actions) exposed a verified embedded browser-pane action. [The CLI reference](https://www.superlogical.com/rex/docs/reference/cli) documents `rex forward open` for opening a forwarded URL in the system browser, not inside a pane. If a newer Rex build exposes an embedded browser, verify its URL-opening API and key routing using sample data first. In particular, `Ctrl+S`, then `o` should remain a Rex binding, while the view needs to receive `Ctrl+E`, `Ctrl+W`, `Ctrl+Enter`, and the navigation keys without host interception. The prototype implements a subset of Vim motions, not a full Vim engine; the existing Neovim overlay is the fallback for exact behavior.

### Loopback server for Quick Look

The standard `rex-annotation install` makes the bundled preview available and prints this optional command. It does not start a server or change certificate trust.

```sh
rex-annotation web-preview --trust-local-certificate
```

Run it in a Rex pane, then Shift+Cmd-click the printed URL. It serves only the sample HTML and its Markdown script on loopback HTTPS, with no agent data or delivery access. The explicit flag allows temporary trust for a one-day certificate scoped to SSL for `localhost` in your login keychain. Press Ctrl+C to stop and remove the certificate. No RexWeb installation or default-browser change is needed. Before relying on the web annotator, test whether Quick Look passes `Ctrl+E`, `Ctrl+W`, and `Ctrl+Enter` to the page.

## Later: opt-in native picker

Prototype the palette with synthetic reply rows first. It supports titles, subtitles, and detail columns, but caps items at 2,000; the current adapter can expose up to 5,000 replies. Preserve access to the full list via the existing picker rather than silently dropping older items. Keep `Esc` back-navigation local until the native handoff proves it can preserve selection and protect unfinished notes.

The prompt API currently asks **all eligible connected apps**, including other devices. The first answer wins, and cancellation affects all of them. Do not send real reply text or excerpts through `rex.ui.pick` until caller-local scoping is documented and verified. A content-free native action chooser is a safer experiment, with no automatic fallback after deliberate cancellation. For a future real picker, gate on server/client support, revalidate the original binding after the wait, and retain the Neovim path when native prompts are unavailable. The prompt must run directly inside a named Rex action, outside `pcall`/`xpcall`; the existing overlay launcher can keep its protected cleanup path after the prompt returns.
