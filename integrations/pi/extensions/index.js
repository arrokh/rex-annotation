import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { startBridge } from '../bridge.js';

const run = promisify(execFile);

async function resolveSession(block) {
  if (process.env.REX_SESSION) return process.env.REX_SESSION;
  const { stdout } = await run('rex', ['--autostart=false', '--timeout', '1s', 'whoami', '--json'], {
    timeout: 1600, maxBuffer: 64 * 1024,
  });
  const location = JSON.parse(stdout);
  if (location.block_id !== block || typeof location.session_id !== 'string' || !location.session_id) {
    throw new Error('Rex could not resolve this Pi pane to an exact session');
  }
  return location.session_id;
}

// An event-driven, local-only bridge. No polling, transcript files, or model calls.
export default function rexAnnotate(pi) {
  let context;
  let bridge;
  let starting;
  pi.on('session_start', async (_event, ctx) => {
    context = ctx;
    const block = process.env.REX_BLOCK;
    if (ctx.mode !== 'tui' || !block || bridge || starting) return;
    try {
      starting = resolveSession(block).then(session => startBridge(() => context, { pid: process.pid,
        session, block, sendMessage: (text, options) => pi.sendUserMessage(text, options) }));
      bridge = await starting;
    } catch (error) { ctx.ui.notify(`Rex annotation bridge unavailable: ${error.message}`, 'warning'); }
    finally { starting = undefined; }
  });
  pi.on('session_shutdown', async () => {
    if (starting) { try { await starting; } catch {} }
    await bridge?.close();
    bridge = undefined;
    context = undefined;
  });
}
