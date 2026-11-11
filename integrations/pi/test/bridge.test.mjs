import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, lstat, mkdir, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createConnection } from 'node:net';
import { renderBranch, renderReplies, startBridge } from '../bridge.js';

const branch = [
  { type: 'message', message: { role: 'system', content: 'HIDDEN SYSTEM' } },
  { type: 'message', message: { role: 'user', content: 'first message above the viewport' } },
  { type: 'message', message: { role: 'assistant', content: [
    { type: 'thinking', thinking: 'HIDDEN THINKING' },
    { type: 'text', text: '| a | b |\n|---|---|\n| 1 | 2 |' },
    { type: 'toolCall', name: 'bash', arguments: { command: 'printf hi' } },
  ] } },
  { type: 'message', message: { role: 'toolResult', toolName: 'bash', content: [{ type: 'text', text: 'original output\nno renderer frame' }] } },
  { type: 'custom_message', display: false, content: 'HIDDEN EXTENSION' },
  { type: 'message', message: { role: 'custom', content: 'HIDDEN UNMARKED EXTENSION' } },
];

test('full active branch is plain text without renderer decorations and preserves legitimate pipes', () => {
  const text = renderBranch(branch);
  assert.match(text, /first message above the viewport/);
  assert.match(text, /\| a \| b \|/);
  assert.match(text, /original output\nno renderer frame/);
  assert.doesNotMatch(text, /│|HIDDEN/);
});

test('reply list contains only visible assistant text in active-branch order', () => {
  const replies = renderReplies([
    { type: 'message', id: 'user', timestamp: '2026-11-10T00:00:00Z', message: { role: 'user', content: 'prompt' } },
    { type: 'message', id: 'tooling', timestamp: '2026-11-10T00:00:01Z', message: { role: 'assistant', content: [
      { type: 'thinking', thinking: 'SECRET' }, { type: 'text', text: 'Visible preamble' },
      { type: 'toolCall', name: 'bash', arguments: { command: 'hidden' } },
    ] } },
    { type: 'message', id: 'tool', message: { role: 'toolResult', content: 'tool output' } },
    { type: 'message', id: 'answer', timestamp: '2026-11-10T00:00:02Z', message: { role: 'assistant', content: [
      { type: 'thinking', thinking: 'SECRET' }, { type: 'text', text: 'Final answer\nwith exact formatting' },
    ] } },
    { type: 'custom_message', display: true, content: 'extension message' },
  ]);
  assert.deepEqual(replies, [
    { id: 'tooling', timestamp: '2026-11-10T00:00:01Z', text: 'Visible preamble' },
    { id: 'answer', timestamp: '2026-11-10T00:00:02Z', text: 'Final answer\nwith exact formatting' },
  ]);
  assert.doesNotMatch(JSON.stringify(replies), /SECRET|hidden|tool output|extension message/);
});

function request(socketPath, payload) {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let data = '';
    socket.setEncoding('utf8'); socket.setTimeout(2000, () => socket.destroy(new Error('timeout')));
    socket.on('connect', () => socket.end(JSON.stringify(payload) + '\n'));
    socket.on('data', chunk => { data += chunk; });
    socket.on('error', reject);
    socket.on('end', () => { try { resolve(JSON.parse(data)); } catch (e) { reject(e); } });
  });
}

test('socket binds exact pane and current session; insert preserves newlines without submitting', async () => {
  const root = await mkdtemp(join(tmpdir(), 'rex-pi-bridge-test-'));
  let editor = 'existing draft\n'; let session = 'conversation-one'; let idle = true;
  const sent = [];
  const ctx = { mode: 'tui', hasUI: true, isIdle: () => idle, hasPendingMessages: () => false,
    sessionManager: { getSessionId: () => session, getBranch: () => branch },
    ui: { getEditorText: () => editor, setEditorText: text => { editor = text; } } };
  const bridge = await startBridge(() => ctx, { root, pid: process.pid, session: 'session:test', block: 'block:test',
    sendMessage: text => sent.push(text) });
  const binding = { version: 1, pid: process.pid, session: 'session:test', block: 'block:test' };
  assert.equal((await lstat(root)).mode & 0o777, 0o700);
  assert.equal((await lstat(bridge.path)).mode & 0o777, 0o600);
  try {
    const snapshot = await request(bridge.path, { ...binding, op: 'snapshot' });
    assert.equal(snapshot.ok, true); assert.equal(snapshot.sessionId, session);
    assert.match(snapshot.text, /first message above the viewport/);
    const replies = await request(bridge.path, { ...binding, op: 'replies' });
    assert.equal(replies.ok, true); assert.equal(replies.sessionId, session);
    assert.deepEqual(replies.replies, [{ id: 'reply-1', timestamp: '', text: '| a | b |\n|---|---|\n| 1 | 2 |' }]);
    const status = await request(bridge.path, { ...binding, op: 'status' });
    assert.equal(status.ok, true); assert.equal(status.sessionId, session); assert.equal(status.text, undefined);
    const payload = '# Terminal annotations\n\n> a | b\n\nComment:\nhi there';
    assert.equal((await request(bridge.path, { ...binding, op: 'insert', sessionId: session, text: payload })).ok, true);
    assert.equal(editor, 'existing draft\n' + payload);
    assert.equal((await request(bridge.path, { ...binding, op: 'send', sessionId: session, text: payload })).ok, true);
    assert.deepEqual(sent, [payload]);
    session = 'conversation-two';
    assert.equal((await request(bridge.path, { ...binding, op: 'insert', sessionId: 'conversation-one', text: 'wrong session' })).ok, false);
    assert.equal((await request(bridge.path, { ...binding, op: 'insert', sessionId: session, text: 'bad\x1b[201~' })).ok, false);
    assert.equal((await request(bridge.path, { ...binding, op: 'send', sessionId: 'conversation-one', text: 'wrong session' })).ok, false);
    idle = false;
    assert.equal((await request(bridge.path, { ...binding, op: 'insert', sessionId: session, text: 'busy' })).ok, false);
    assert.equal((await request(bridge.path, { ...binding, op: 'send', sessionId: session, text: 'busy' })).ok, false);
    assert.deepEqual(sent, [payload]);
    assert.equal((await request(bridge.path, { ...binding, block: 'block:other', op: 'snapshot' })).ok, false);
    assert.equal(editor, 'existing draft\n' + payload);
  } finally {
    await bridge.close();
    await assert.rejects(lstat(bridge.path), { code: 'ENOENT' });
    await rm(root, { recursive: true, force: true });
  }
});

test('oversized history and reply lists fail visibly instead of truncating', () => {
  assert.throws(() => renderBranch([{ type: 'message', message: { role: 'user', content: 'x'.repeat(4 * 1024 * 1024) } }]), /exceeds 4 MiB/);
  assert.throws(() => renderReplies([{ type: 'message', message: {
    role: 'assistant', content: [{ type: 'text', text: 'x'.repeat(4 * 1024 * 1024 + 1) }],
  } }]), /exceed 4 MiB/);
  assert.throws(() => renderReplies(Array.from({ length: 5001 }, (_, index) => ({
    type: 'message', id: String(index), message: { role: 'assistant', content: 'ok' },
  }))), /5,000 entries/);
});

test('a symlink socket directory is rejected without altering its target', async () => {
  const root = await mkdtemp(join(tmpdir(), 'rex-pi-symlink-test-'));
  try {
    await mkdir(join(root, 'real'), { mode: 0o755 });
    await symlink(join(root, 'real'), join(root, 'link'));
    await assert.rejects(startBridge(() => null, { root: join(root, 'link'), pid: process.pid, session: 's', block: 'b' }), /Unsafe/);
    assert.equal((await lstat(join(root, 'real'))).mode & 0o777, 0o755);
  } finally { await rm(root, { recursive: true, force: true }); }
});
