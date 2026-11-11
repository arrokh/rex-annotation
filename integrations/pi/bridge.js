import { createServer } from 'node:net';
import { mkdir, lstat, chmod } from 'node:fs/promises';
import { join } from 'node:path';
import { stripVTControlCharacters } from 'node:util';

export const LIMIT = 4 * 1024 * 1024;
export const socketRoot = () => `/tmp/rex-annotate-pi-${process.getuid()}`;

export function renderBranch(entries) {
  const parts = ['# Pi conversation'];
  let bytes = Buffer.byteLength(parts[0]);
  const add = (title, value) => {
    if (typeof value !== 'string' || !value.length) return;
    const part = `## ${title}\n\n${stripVTControlCharacters(value)}`;
    bytes += Buffer.byteLength(part) + 2;
    if (bytes > LIMIT) throw new Error('Pi conversation exceeds 4 MiB; no partial snapshot was returned');
    parts.push(part);
  };
  for (const entry of entries) {
    if (entry.type === 'custom_message') {
      if (entry.display === true) add('Extension message', contentText(entry.content));
      continue;
    }
    if (entry.type !== 'message') continue;
    const msg = entry.message;
    if (!msg || !['user', 'assistant', 'toolResult', 'custom'].includes(msg.role)) continue;
    if (msg.role === 'custom' && msg.display !== true) continue;
    const title = { user: 'User', assistant: 'Assistant', toolResult: 'Tool result', custom: 'Extension message' }[msg.role];
    if (typeof msg.content === 'string') add(title, msg.content);
    else for (const block of msg.content ?? []) {
      if (block.type === 'text') add(title, block.text);
      else if (block.type === 'toolCall') add('Tool call: ' + block.name, JSON.stringify(block.arguments, null, 2));
      // Hidden thinking, system prompts, image data, and extension state are not exported.
    }
  }
  return parts.join('\n\n');
}
export function renderReplies(entries) {
  const replies = [];
  let bytes = 0;
  for (const entry of entries) {
    if (entry.type !== 'message' || entry.message?.role !== 'assistant') continue;
    const text = stripVTControlCharacters(contentText(entry.message.content));
    if (!text.trim()) continue;
    bytes += Buffer.byteLength(text);
    if (bytes > LIMIT) throw new Error('Pi replies exceed 4 MiB; no partial list was returned');
    replies.push({
      id: typeof entry.id === 'string' ? entry.id : `reply-${replies.length + 1}`,
      timestamp: typeof entry.timestamp === 'string' ? entry.timestamp : '',
      text,
    });
    if (replies.length > 5000) throw new Error('Pi reply list exceeds 5,000 entries; no partial list was returned');
  }
  return replies;
}
function contentText(content) {
  return typeof content === 'string' ? content : (content ?? []).filter(b => b.type === 'text').map(b => b.text).join('\n');
}

export async function startBridge(getContext, options) {
  const { pid, session, block, sendMessage } = options;
  const root = options.root ?? socketRoot();
  await mkdir(root, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
  const stat = await lstat(root);
  if (!stat.isDirectory() || stat.uid !== process.getuid()) throw new Error('Unsafe Pi annotation socket directory');
  await chmod(root, 0o700);
  const path = join(root, `${pid}.sock`);
  const connections = new Set();
  const server = createServer({ allowHalfOpen: true }, socket => {
    connections.add(socket);
    socket.setTimeout(2500, () => socket.destroy());
    socket.on('error', () => {});
    socket.on('close', () => connections.delete(socket));
    let data = ''; let handled = false;
    socket.setEncoding('utf8');
    socket.on('data', chunk => {
      if (handled) return;
      data += chunk;
      if (Buffer.byteLength(data) > LIMIT * 2) { handled = true; socket.end(JSON.stringify({ ok: false, error: 'Request too large' })); return; }
      if (!data.includes('\n')) return;
      handled = true;
      try {
        const request = JSON.parse(data.trim());
        if (request.version !== 1 || request.pid !== pid || request.session !== session || request.block !== block)
          throw new Error('Pi process/pane binding changed');
        const ctx = getContext();
        if (!ctx || ctx.mode !== 'tui') throw new Error('Pi editor is unavailable');
        const sessionId = ctx.sessionManager.getSessionId();
        if (request.op === 'snapshot') {
          socket.end(JSON.stringify({ ok: true, pid, sessionId, text: renderBranch(ctx.sessionManager.getBranch()) }));
        } else if (request.op === 'replies') {
          socket.end(JSON.stringify({ ok: true, pid, sessionId, replies: renderReplies(ctx.sessionManager.getBranch()) }));
        } else if (request.op === 'status') {
          socket.end(JSON.stringify({ ok: true, pid, sessionId }));
        } else if (request.op === 'insert' || request.op === 'send') {
          if (request.sessionId !== sessionId) throw new Error('Pi conversation changed; open a new annotation view');
          if (!ctx.isIdle() || ctx.hasPendingMessages()) throw new Error('Pi is busy; wait for its editable prompt');
          const payload = request.text;
          if (typeof payload !== 'string' || !payload.trim() || Buffer.byteLength(payload) > LIMIT || /[\x00-\x08\x0b-\x1f\x7f]/.test(payload))
            throw new Error('Invalid annotation text');
          if (request.op === 'send') {
            if (typeof sendMessage !== 'function') throw new Error('Pi send action is unavailable');
            sendMessage(payload); // Only the explicit Rex Send action reaches this path.
            socket.end(JSON.stringify({ ok: true, pid, sessionId }));
          } else {
            const combined = ctx.ui.getEditorText() + payload;
            ctx.ui.setEditorText(combined); // Editor API, not keystrokes or sendUserMessage: never submits.
            if (ctx.ui.getEditorText() !== combined) throw new Error('Editor changed inserted text; inspect draft before retrying');
            ctx.ui.notify?.('Annotations inserted into the draft (not submitted).', 'info');
            socket.end(JSON.stringify({ ok: true, pid, sessionId }));
          }
        } else throw new Error('Unsupported Pi annotation request');
      } catch (error) { socket.end(JSON.stringify({ ok: false, error: error.message })); }
    });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(path, resolve);
  });
  try { await chmod(path, 0o600); }
  catch (error) { await new Promise(resolve => server.close(resolve)); throw error; }
  server.unref();
  return { path, close: async () => {
    for (const socket of connections) socket.destroy();
    await new Promise(resolve => server.close(resolve));
  } };
}
