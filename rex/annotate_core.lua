-- In-memory annotation model and Rex API boundary. No editor configuration or disk state.
local M = {}

local function text(value)
  assert(type(value) == "string" and value:find("%S"), "Text must not be blank")
  assert(not value:find("[%z\1-\8\11-\31\127]"), "Unsupported control character in text")
  return value
end

function M.draft(source)
  local draft = { source = source, notes = {}, next_id = 0, dirty = false }
  function draft:add(quote, comment, range)
    text(quote)
    text(comment)
    self.next_id = self.next_id + 1
    table.insert(self.notes, { id = self.next_id, quote = quote, comment = comment, range = range })
    self.dirty = true
    return self.next_id
  end
  function draft:edit(id, comment)
    text(comment)
    for _, note in ipairs(self.notes) do
      if note.id == id then note.comment = comment; self.dirty = true; return end
    end
    error("Annotation no longer exists")
  end
  function draft:remove(id)
    for i, note in ipairs(self.notes) do
      if note.id == id then table.remove(self.notes, i); self.dirty = #self.notes > 0; return end
    end
    error("Annotation no longer exists")
  end
  function draft:format()
    if #self.notes == 0 then return "" end
    local parts = { "# Terminal annotations" }
    for i, note in ipairs(self.notes) do
      parts[#parts + 1] = "## " .. i .. "\n> " .. note.quote:gsub("\n", "\n> ") .. "\n\nComment:\n" .. note.comment
    end
    return table.concat(parts, "\n\n")
  end
  return draft
end

local function source_pane(view, target)
  local function find(node)
    if type(node) ~= "table" then return nil end
    if node.block_id == target.block_id then return node.rect end
    if node.split then return find(node.split.before) or find(node.split.after) end
  end
  for _, window in ipairs(view.windows or {}) do
    if window.window_id == target.window_id then
      for _, layer in ipairs(window.layers or {}) do
        local rect = layer.state ~= "minimized" and find(layer.layout)
        if rect then
          -- Rex retains unzoomed layout rects while the zoomed block fills the window.
          if window.zoomed_block_id == target.block_id then rect = { 0, 0, 1, 1 } end
          return window, rect
        end
      end
    end
  end
end

function M.overlay_bounds(view, target)
  local _, rect = source_pane(view, target)
  assert(rect and #rect == 4, "Source pane geometry is unavailable; focus the target and retry")
  for _, value in ipairs(rect) do assert(type(value) == "number", "Invalid source pane geometry") end
  assert(rect[3] > 0 and rect[4] > 0, "Source pane has no visible area")
  -- Keep the source pane's width/height, but center the overlay in the Rex window.
  local width, height = rect[3], rect[4] * 0.9
  return { (1 - width) / 2, (1 - height) / 2, width, height }
end

function M.restore_focus(call, target, overlay_block)
  if not overlay_block or not target.window_id then return false end
  local view = call("session.view", { session_id = target.session_id })
  local window = source_pane(view, target)
  if not window or view.active_window_id ~= target.window_id
    or window.focused_block_id ~= overlay_block then return false end
  -- Do this BEFORE the overlay process exits: automatic close chooses another
  -- tiled pane, not necessarily the pane from which annotation was requested.
  call("session.focus_block", { session_id = target.session_id, block_id = target.block_id })
  return true
end

-- `call` is the Rex API system boundary, not a terminal-output scraper.
function M.capture(call, target, limit)
  limit = limit or 4 * 1024 * 1024
  local started = os.time()
  local function read(method, args)
    assert(os.time() - started < 15, "Capture exceeded 15 seconds; retry with less output")
    return call("com.superlogical.terminal." .. method, {
      session_id = target.session_id, block_id = target.block_id, args = args,
    })
  end
  local first = read("format", { format = "text", trim = false, unwrap = true, max_bytes = 262144 })
  local content = first.content
  assert(type(content) == "string", "Rex returned no snapshot")
  assert(#content <= limit and (not first.total or first.total <= limit), "Snapshot exceeds 4 MiB; use a smaller source")
  if not first.id then
    assert(first.eof ~= false and (not first.total or first.total == #content), "Incomplete snapshot")
    return content
  end
  assert(first.id > 0, "Rex returned an unsafe snapshot reference")
  for _ = 1, 128 do
    local part = read("blob_read", { id = first.id, offset = #content, max_bytes = 262144 })
    assert(part.id == first.id and type(part.data) == "string", "Snapshot reference changed")
    assert(#part.data > 0 or part.eof, "Snapshot pagination made no progress")
    content = content .. part.data
    assert(#content <= limit, "Snapshot exceeds 4 MiB; use a smaller source")
    if part.eof then
      assert(not part.total or part.total == #content, "Incomplete snapshot")
      return content
    end
  end
  error("Snapshot pagination exceeded its limit")
end

function M.identity(process)
  if process.last_exit and process.last_exit ~= vim.NIL then return nil end
  local p = process.foreground
  if type(p) ~= "table" or type(p.pid) ~= "number" then return nil end
  local path, script, argv0 = p.path or "", p.script or "", p.argv0 or ""
  local base = path:match("([^/]+)$") or ""
  local agent
  if base == "codex" then
    agent = "Codex"
  elseif base == "claude" or path:match("/claude/versions/[%d.]+$") then
    agent = "Claude Code"
  elseif base:match("^node") and (argv0 == "pi" or script:match("/pi%-coding%-agent/dist/.*cli%.js$")) then
    agent = "Pi"
  end
  if not agent then return nil end
  return { agent = agent, pid = p.pid, path = path, script = script, argv0 = argv0 }
end

local function same_process(left, right)
  return left and right and left.agent == right.agent and left.pid == right.pid
    and left.path == right.path and left.script == right.script and left.argv0 == right.argv0
end

function M.insert(call, target, original, payload, pi_insert, validate_session)
  text(payload)
  assert(original, "No recognized agent was captured; copy instead")
  local args = { session_id = target.session_id, block_id = target.block_id, args = vim.empty_dict() }
  local current = M.identity(call("com.superlogical.terminal.process", args))
  assert(same_process(current, original), "Destination process changed; copy instead")
  if pi_insert then
    assert(current.agent == "Pi", "Editor bridge is only supported for Pi")
    return pi_insert(payload) -- Exact text through Pi's editor API, independent of Vim mode.
  end
  if validate_session then validate_session() end
  local modes = call("com.superlogical.terminal.modes", args)
  local bracketed = false
  for _, mode in ipairs(modes.modes or {}) do
    if mode.number == 2004 and not mode.ansi and mode.set == true then bracketed = true end
  end
  assert(bracketed, "Destination does not enable bracketed paste; copy instead")
  -- Never retry this side effect: a timeout can mean the paste already happened.
  return call("block.event", { session_id = target.session_id, block_id = target.block_id,
    event = { type = "paste", payload = { text = payload } } })
end

function M.send(call, target, original, payload, pi_send, validate_session)
  text(payload)
  assert(original, "No recognized agent was captured; copy instead")
  local args = { session_id = target.session_id, block_id = target.block_id, args = vim.empty_dict() }
  local current = M.identity(call("com.superlogical.terminal.process", args))
  assert(same_process(current, original), "Destination process changed; copy instead")
  if pi_send then
    assert(current.agent == "Pi", "Editor bridge is only supported for Pi")
    return pi_send(payload)
  end
  if validate_session then validate_session() end
  local modes = call("com.superlogical.terminal.modes", args)
  local bracketed = false
  for _, mode in ipairs(modes.modes or {}) do
    if mode.number == 2004 and not mode.ansi and mode.set == true then bracketed = true end
  end
  assert(bracketed, "Destination does not enable bracketed paste; copy instead")
  call("block.event", { session_id = target.session_id, block_id = target.block_id,
    event = { type = "paste", payload = { text = payload } } })
  if validate_session then
    local valid, failure = pcall(validate_session)
    assert(valid, "Session changed after paste; message was not submitted. Inspect the draft before retrying. " .. tostring(failure))
  end
  current = M.identity(call("com.superlogical.terminal.process", args))
  assert(same_process(current, original),
    "Destination process changed after paste; message was not submitted. Inspect the draft before retrying")
  local ok, result = pcall(call, "block.event", { session_id = target.session_id, block_id = target.block_id,
    event = { type = "key", payload = { key = "enter" } } })
  assert(ok, "Paste was sent but Enter failed; inspect the draft before retrying. " .. tostring(result))
  return result
end

-- One local request per action. Socket inode contains no transcript or handoff payload.
function M.pi_request(target, pid, request)
  local uv = vim.uv or vim.loop
  local root = "/tmp/rex-annotate-pi-" .. uv.getuid()
  for _, item in ipairs({ { root, "directory" }, { root .. "/" .. pid .. ".sock", "socket" } }) do
    local stat = uv.fs_lstat(item[1])
    assert(stat and stat.type == item[2] and stat.uid == uv.getuid() and bit.band(stat.mode, 63) == 0,
      "Pi annotation bridge unavailable. Install rex-annotation in Pi; reload that Pi only when it is safe to clear session-only auth.")
  end
  local pipe = uv.new_pipe(false)
  local done, failure = false, nil
  local chunks, size = {}, 0
  local function finish(err)
    if done then return end
    failure, done = err, true
    if not pipe:is_closing() then pipe:close() end
  end
  pipe:connect(root .. "/" .. pid .. ".sock", function(err)
    if err then finish(err); return end
    pipe:read_start(function(read_error, chunk)
      if read_error then finish(read_error); return end
      if not chunk then finish(); return end
      size = size + #chunk
      if size > 12 * 1024 * 1024 then finish("Pi bridge response is too large"); return end
      chunks[#chunks + 1] = chunk
    end)
    pipe:write(vim.json.encode({ version = 1, pid = pid, session = target.session_id,
      block = target.block_id, op = request.op, sessionId = request.sessionId, text = request.text }) .. "\n",
      function(write_error) if write_error then finish(write_error) end end)
  end)
  if not vim.wait(3000, function() return done end, 10) then finish("Pi bridge timed out; inspect the original draft before retrying") end
  assert(not failure, failure)
  local response = vim.json.decode(table.concat(chunks))
  assert(type(response) == "table", "Invalid Pi bridge response")
  assert(response.ok == true, response.error or "Pi annotation request failed")
  assert(response.pid == pid and type(response.sessionId) == "string", "Pi bridge identity changed")
  return response
end

-- Native Codex/Claude adapters read only an explicitly registered transcript.
function M.agent_request(target, original, request)
  local agents = { Codex = "codex", ["Claude Code"] = "claude" }
  local agent = original and agents[original.agent]
  assert(agent, "No supported native transcript adapter")
  assert(request.op == "replies" or request.op == "validate", "Unsupported agent annotation request")
  local source = debug.getinfo(1, "S").source:gsub("^@", "")
  local root = assert(source:match("^(.*[/\\])"), "Missing plugin directory") .. "../"
  local command = { "python3", root .. "integrations/session_replies.py", request.op,
    "--agent", agent, "--pid", tostring(original.pid), "--session", target.session_id, "--block", target.block_id }
  if request.sessionId then
    command[#command + 1] = "--conversation"
    command[#command + 1] = request.sessionId
  end
  local result = vim.system(command, { text = true, timeout = 6000 }):wait()
  assert(result.code == 0, "Agent session unavailable; notes kept. " .. (result.stderr or result.stdout or ""))
  assert(#(result.stdout or "") <= 12 * 1024 * 1024, "Agent reply response is too large")
  local response = vim.json.decode(result.stdout)
  assert(type(response) == "table" and type(response.sessionId) == "string", "Invalid agent session response")
  assert(not request.sessionId or response.sessionId == request.sessionId, "Agent conversation changed; open a new annotation pane")
  return response
end

return M
