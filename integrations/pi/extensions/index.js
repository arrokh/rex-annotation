import { startBridge } from '../bridge.js';

// An event-driven, local-only bridge. No polling, transcript files, or model calls.
export default function rexAnnotate(pi) {
  let context;
  let bridge;
  let starting;
  pi.on('session_start', async (_event, ctx) => {
    context = ctx;
    if (ctx.mode !== 'tui' || !process.env.REX_SESSION || !process.env.REX_BLOCK || bridge) return;
    try {
      starting = startBridge(() => context, { pid: process.pid,
        session: process.env.REX_SESSION, block: process.env.REX_BLOCK,
        sendMessage: text => pi.sendUserMessage(text) });
      bridge = await starting;
    } catch (error) { ctx.ui.notify(`Rex annotation bridge unavailable: ${error.message}`, 'warning'); }
  });
  pi.on('session_shutdown', async () => {
    if (starting) { try { await starting; } catch {} }
    await bridge?.close();
    bridge = undefined;
    context = undefined;
  });
}
