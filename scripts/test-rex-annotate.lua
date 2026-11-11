-- Run with: nvim --headless --noplugin -u NONE -i NONE -n -l scripts/test-rex-annotate.lua
local root = vim.fn.getcwd() .. "/rex/"
local core = dofile(root .. "annotate_core.lua")
local passed = 0
local function test(name, run)
  local ok, err = pcall(run)
  if not ok then error(name .. ": " .. tostring(err), 0) end
  passed = passed + 1
  print("PASS " .. name)
end
local function eq(expected, actual) assert(vim.deep_equal(expected, actual), vim.inspect(actual)) end
local function bounds_eq(expected, actual)
  eq(#expected, #actual)
  for i, value in ipairs(expected) do assert(math.abs(value - actual[i]) < 1e-10, vim.inspect(actual)) end
end

test("collect, edit, and remove notes without changing the original quote", function()
  local draft = core.draft("block:source")
  local id = draft:add("alpha\nbeta", "explain", { 1, 0, 2, 4 })
  eq("# Terminal annotations\n\n## 1\n> alpha\n> beta\n\nComment:\nexplain", draft:format())
  draft:edit(id, "why?\nplease clarify")
  eq("# Terminal annotations\n\n## 1\n> alpha\n> beta\n\nComment:\nwhy?\nplease clarify", draft:format())
  draft:remove(id)
  eq("", draft:format())
end)

test("snapshot pagination uses byte offsets and a single blob, without trimming", function()
  local target = { session_id = "session:test", block_id = "block:source" }
  local snapshot = core.capture(function(method, args)
    eq(target.session_id, args.session_id)
    eq(target.block_id, args.block_id)
    if method == "com.superlogical.terminal.format" then
      eq(false, args.args.trim)
      eq(true, args.args.unwrap)
      return { content = "é  \n", id = 17, total = 9 }
    end
    eq("com.superlogical.terminal.blob_read", method)
    eq(17, args.args.id)
    eq(5, args.args.offset)
    return { data = "tail", id = 17, eof = true, total = 9 }
  end, target)
  eq("é  \ntail", snapshot)
end)

test("insertion targets the saved recognized foreground and sends exactly one paste", function()
  local process = { foreground = { pid = 42, name = "node", path = "/bin/node", argv0 = "pi" } }
  local identity = core.identity(process)
  eq("Pi", identity.agent)
  local events = {}
  core.insert(function(method, args)
    if method == "com.superlogical.terminal.process" then
      eq('{"args":{}}', vim.json.encode({ args = args.args }))
      return process
    end
    if method == "com.superlogical.terminal.modes" then
      return { modes = { { number = 2004, set = true } } }
    end
    eq("block.event", method)
    events[#events + 1] = args
    return {}
  end, { session_id = "session:test", block_id = "block:source" }, identity, "quote\ncomment")
  eq({ { session_id = "session:test", block_id = "block:source",
    event = { type = "paste", payload = { text = "quote\ncomment" } } } }, events)
end)

test("explicit Send pastes then submits only after a separate service call", function()
  local process = { foreground = { pid = 42, name = "node", path = "/bin/node", argv0 = "pi" } }
  local original = core.identity(process)
  local events = {}
  core.send(function(method, args)
    if method == "com.superlogical.terminal.process" then return process end
    if method == "com.superlogical.terminal.modes" then return { modes = { { number = 2004, set = true } } } end
    events[#events + 1] = args.event
    return {}
  end, { session_id = "session:test", block_id = "block:source" }, original, "quote\ncomment")
  eq({
    { type = "paste", payload = { text = "quote\ncomment" } },
    { type = "key", payload = { key = "enter" } },
  }, events)
  local sent
  core.send(function(method)
    if method == "com.superlogical.terminal.process" then return process end
    error("Pi send must use its explicit bridge callback")
  end, { session_id = "session:test", block_id = "block:source" }, original, "payload", function(payload)
    sent = payload
  end)
  eq("payload", sent)
end)

test("reply picker shows relative time and preview without IDs or absolute dates, then opens exact text", function()
  local view = dofile(root .. "annotate_view.lua")
  local target = { session_id = "session:test", block_id = "block:source" }
  local picker = view.pick_replies({
    { id = "private-old-id", hash = "deadbeef", timestamp = "invalid timestamp", text = "older reply\nsecond line" },
    { id = "private-latest-id", hash = "facefeed", timestamp = os.date("!%Y-%m-%dT%H:%M:%SZ", os.time() - 125),
      text = "latest exact reply\nwith Unicode é and pipes |" },
  }, target, {})
  local lines = vim.api.nvim_buf_get_lines(picker.picker, 0, -1, false)
  eq("    2m  latest exact reply", lines[3])
  eq("     ?  older reply", lines[4])
  assert(not table.concat(lines, "\n"):find("PI REPLIES", 1, true))
  assert(not table.concat(lines, "\n"):find("private-latest-id", 1, true))
  assert(not table.concat(lines, "\n"):find("deadbeef", 1, true))
  assert(not table.concat(lines, "\n"):find("%d%d%d%d%-", 1))
  assert(vim.wo[0].winbar:find("PI REPLIES", 1, true))
  vim.fn.feedkeys(vim.keycode("<CR>"), "xt")
  local session = picker.editor
  assert(session)
  eq({ "latest exact reply", "with Unicode é and pipes |" }, vim.api.nvim_buf_get_lines(session.source, 0, -1, false))
  session:close(true)
end)

test("reply picker supports another agent title and human-friendly future timestamps", function()
  local view = dofile(root .. "annotate_view.lua")
  local future = os.date("!%Y-%m-%dT%H:%M:%SZ", os.time() + 125)
  local picker = view.pick_replies({ { id = "hidden-id", timestamp = future, text = "future preview" } },
    { block_id = "b" }, {}, "Claude Code")
  local lines = vim.api.nvim_buf_get_lines(picker.picker, 0, -1, false)
  eq("   +2m  future preview", lines[3])
  assert(not lines[3]:find("hidden-id", 1, true))
  assert(vim.wo[0].winbar:find("Claude Code REPLIES", 1, true))
  vim.api.nvim_buf_delete(picker.picker, { force = true })
end)

test("reply time column stays fixed across compact units and Unicode previews", function()
  local view = dofile(root .. "annotate_view.lua")
  local cases = {
    { 2, "now" }, { 120, "2m" }, { 15 * 3600, "15h" }, { 7 * 86400, "7d" },
    { 60 * 86400, "2mo" }, { 2 * 365 * 86400, "2y" }, { -7200, "+2h" },
  }
  local replies = {}
  local now = os.time()
  for _, case in ipairs(cases) do
    replies[#replies + 1] = { timestamp = os.date("!%Y-%m-%dT%H:%M:%SZ", now - case[1]), text = "猫 preview" }
  end
  local picker = view.pick_replies(replies, { block_id = "b" }, {})
  local lines = vim.api.nvim_buf_get_lines(picker.picker, 0, -1, false)
  for index, case in ipairs(cases) do
    local row = lines[#lines - index + 1]
    eq(string.format("%6s  猫 preview", case[2]), row)
    eq(8, vim.fn.strdisplaywidth(row:sub(1, row:find("猫", 1, true) - 1)))
  end
  vim.api.nvim_buf_delete(picker.picker, { force = true })
end)

test("explicit Send needs no typed confirmation and closes only after success", function()
  local view = dofile(root .. "annotate_view.lua")
  local sent, quit = {}, 0
  local session = view.open("alpha beta", { block_id = "b" }, {
    send = function(payload) sent[#sent + 1] = payload end,
    quit = function() quit = quit + 1 end,
  })
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "comment" .. vim.keycode("<C-s>"), "xt")
  local input = vim.fn.input
  vim.fn.input = function() error("Send must not request typed confirmation") end
  vim.fn.feedkeys("S", "xt")
  vim.fn.input = input
  eq(1, #sent)
  assert(sent[1]:find("comment", 1, true))
  eq(1, quit)
  eq(false, vim.api.nvim_buf_is_valid(session.source))
end)

test("Pi draft insertion skips confirmation and auto-closes only after success", function()
  local view = dofile(root .. "annotate_view.lua")
  local inserted, quit = nil, 0
  local session = view.open("alpha beta", { block_id = "b" }, {
    insert_requires_confirmation = false,
    insert = function(payload) inserted = payload end,
    quit = function() quit = quit + 1 end,
  })
  local confirm = vim.fn.confirm
  vim.fn.confirm = function() error("Pi draft insertion should not ask for confirmation") end
  local ok, err = pcall(vim.fn.feedkeys, "v4l" .. vim.keycode("<CR>") .. "why" .. vim.keycode("<C-s>") .. "s", "xt")
  vim.fn.confirm = confirm
  assert(ok, err)
  assert(inserted:find("Comment:\nwhy", 1, true))
  eq(1, quit)
  eq(false, vim.api.nvim_buf_is_valid(session.source))
end)

test("failed insert and Send retain notes and leave the overlay open", function()
  local view = dofile(root .. "annotate_view.lua")
  local quit = 0
  local session = view.open("alpha", { block_id = "b" }, {
    insert_requires_confirmation = false,
    insert = function() error("insert failed") end,
    send = function() error("send failed") end,
    quit = function() quit = quit + 1 end,
  })
  session.draft:add("alpha", "keep this note", { 1, 0, 1, 5 })
  local payload = session:payload()
  vim.fn.feedkeys("sS", "xt")
  eq(payload, session:payload())
  eq(true, vim.api.nvim_buf_is_valid(session.source))
  eq(0, quit)
  session:close(true)
end)

test("non-Pi insertion retains its editable-prompt confirmation", function()
  local view = dofile(root .. "annotate_view.lua")
  local inserted
  local session = view.open("alpha", { block_id = "b" }, { insert = function(payload) inserted = payload end })
  session.draft:add("alpha", "note", { 1, 0, 5 })
  local confirm = vim.fn.confirm
  local calls = 0
  vim.fn.confirm = function(message)
    calls = calls + 1
    assert(message:find("editable prompt", 1, true))
    return 1
  end
  local ok, err = pcall(vim.fn.feedkeys, "s", "xt")
  vim.fn.confirm = confirm
  assert(ok, err)
  eq(1, calls)
  eq(nil, inserted)
  assert(session:payload():find("Comment:\nnote", 1, true))
  session:close(true)
end)

test("Vim selection attaches the exact quote and multiline comment in the view", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha beta\ngamma delta", { session_id = "session:test", block_id = "block:source" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  -- Exercise selection, the real comment editor, and its save mapping in one input stream.
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "why?" .. vim.keycode("<CR>") .. "clarify" .. vim.keycode("<C-s>"), "xt")
  eq("# Terminal annotations\n\n## 1\n> alpha\n\nComment:\nwhy?\nclarify", session:payload())
  session:close(true)
end)

test("annotated spans use exact UTF-8 byte ranges and linewise ranges include newline", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("é猫 tail\nsecond\nlast", { block_id = "b" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("vl" .. vim.keycode("<CR>") .. "unicode" .. vim.keycode("<C-s>"), "xt")
  eq({ 1, 0, 1, 5 }, vim.list_slice(session.draft.notes[1].range, 1, 4))
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  vim.fn.feedkeys("V" .. vim.keycode("<CR>") .. "linewise" .. vim.keycode("<C-s>"), "xt")
  eq({ 2, 0, 3, 0 }, vim.list_slice(session.draft.notes[2].range, 1, 4))
  assert(session:payload():find("> second\n> \n\nComment:\nlinewise", 1, true))
  local spans = {}
  for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(session.source, session.namespace, 0, -1, { details = true })) do
    if mark[4].hl_group then spans[#spans + 1] = mark end
  end
  eq(2, #spans)
  eq({ 0, 0, 0, 5, "Visual" }, { spans[1][2], spans[1][3], spans[1][4].end_row,
    spans[1][4].end_col, spans[1][4].hl_group })
  eq({ 1, 0, 2, 0, "Visual" }, { spans[2][2], spans[2][3], spans[2][4].end_row,
    spans[2][4].end_col, spans[2][4].hl_group })
  session:close(true)
end)

test("detail help remains complete through resize without changing snapshot bytes", function()
  local view = dofile(root .. "annotate_view.lua")
  local snapshot = "first line\nsecond é line\nthird"
  local session = view.open(snapshot, { block_id = "b" }, {}, string.rep("detail%猫", 12))
  local header_win
  for _, candidate in ipairs(vim.api.nvim_list_wins()) do
    if candidate ~= vim.api.nvim_get_current_win() then header_win = candidate end
  end
  assert(header_win)
  for _, size in ipairs({ { 40, 20 }, { 60, 24 }, { 120, 35 }, { 40, 20 } }) do
    vim.o.columns, vim.o.lines = size[1], size[2]
    vim.api.nvim_exec_autocmds("VimResized", {})
    vim.cmd("redraw")
    local header_lines = vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(header_win), 0, -1, false)
    local rendered = table.concat(header_lines, "\n")
    assert(#header_lines <= vim.api.nvim_win_get_height(header_win), "header rows are vertically clipped")
    for _, line in ipairs(header_lines) do
      assert(vim.fn.strdisplaywidth(line) <= vim.api.nvim_win_get_width(header_win), "header line is horizontally clipped")
    end
    for _, help in ipairs({ "v/V select", "Enter note", "m edit", "p preview", "y copy", "s insert", "S send now", "q close" }) do
      assert(rendered:find(help, 1, true), "missing header action " .. help)
    end
    assert(vim.api.nvim_win_get_height(header_win) >= 2)
    assert(vim.api.nvim_win_get_height(header_win) < size[2])
  end
  eq(snapshot, table.concat(vim.api.nvim_buf_get_lines(session.source, 0, -1, false), "\n"))
  local header_buf = vim.api.nvim_win_get_buf(header_win)
  session:close(true)
  eq(false, vim.api.nvim_buf_is_valid(header_buf))
end)

test("normal Enter opens the current logical line as a newline-inclusive default", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("first\ncurrent line\nlast", { block_id = "block%source" }, {}, "Codex% REPLY")
  local header_win
  for _, candidate in ipairs(vim.api.nvim_list_wins()) do
    if candidate ~= vim.api.nvim_get_current_win() then header_win = candidate end
  end
  assert(header_win and vim.api.nvim_win_is_valid(header_win))
  local header_lines = vim.api.nvim_buf_get_lines(vim.api.nvim_win_get_buf(header_win), 0, -1, false)
  eq("Codex% REPLY", header_lines[1])
  local help = table.concat(header_lines, "\n")
  for _, action in ipairs({ "v/V select", "Enter note", "m edit", "p preview", "y copy", "s insert", "S send now", "q close" }) do
    assert(help:find(action, 1, true), action)
  end
  assert(vim.wo[0].statusline:find("block%%source", 1, true))
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  vim.fn.feedkeys(vim.keycode("<CR>") .. "explain" .. vim.keycode("<C-s>"), "xt")
  eq("current line\n", session.draft.notes[1].quote)
  eq({ 2, 0, 3, 0 }, vim.list_slice(session.draft.notes[1].range, 1, 4))
  session:close(true)
end)

test("launcher uses explicit source window, local client and an isolated Neovim argv", function()
  local action, created
  local bindings = {}
  _G.rex = {
    action = function(definition)
      if definition.name == "annotate_open" then action = definition end
    end,
    bind = function(chord, name) bindings[chord] = name end,
    json = { encode = vim.json.encode },
    exec = function() return { ok = true } end,
    call = function(method, args)
      if method == "session.describe_block" then return { block = { block_id = "block:source",
        creator_name = "com.superlogical.terminal", window_id = "window:source", host_id = "host:local" } } end
      if method == "server.status" then return { host_id = "host:local" } end
      if method == "client.inspect" then return { client = { info = { platform = "macos" },
        principal = { transport = "unix" } } } end
      if method == "session.list_blocks" then return { blocks = {} } end
      if method == "session.view" then return { windows = { { window_id = "window:source", layers = { {
        layout = { block_id = "block:source", rect = { 0.625, 0, 0.375, 1 } },
      } } } } } end
      if method == "session.new_layer" then created = args; return { layer_id = "layer:owned", block_ids = { "block:owned" } } end
      if method == "session.disown_block" then eq({ "block:owned" }, args.block_ids); return {} end
      error(method)
    end,
  }
  local xdg_config_home = vim.env.XDG_CONFIG_HOME
  vim.env.XDG_CONFIG_HOME = vim.fn.getcwd()
  dofile(root .. "annotate.lua")
  eq("annotate_open", bindings["ctrl+s>o"])
  eq(nil, bindings["ctrl+s>shift+a"])
  eq(nil, bindings["ctrl+s>a"])
  action.run({ session_id = "session:test", block_id = "block:source", client_id = "client:local" }, {})
  eq("window:source", created.window_id)
  eq("session:test", created.session_id)
  bounds_eq({ 0.3125, 0.05, 0.375, 0.9 }, created.bounds)
  local options = created.layout.block.options
  eq("none", options.shell)
  eq(false, options.login)
  assert(vim.tbl_contains(options.command, "NONE"))
  assert(vim.tbl_contains(options.command, "--noplugin"))
  local command_text = table.concat(options.command, "\n")
  assert(command_text:find(root, 1, true), "launcher must resolve helpers from the standalone rex/ directory")
  assert(command_text:find("block:source", 1, true))
  local open = io.open
  io.open = function(path, ...)
    if path:find("annotate_view.lua", 1, true) then
      assert(path:find(root, 1, true), "launcher resolved an annotation helper outside standalone rex/")
      return nil, "missing fixture helper"
    end
    return open(path, ...)
  end
  created = nil
  local ok, err = pcall(action.run, { session_id = "session:test", block_id = "block:source", client_id = "client:local" }, {})
  io.open = open
  eq(false, ok)
  assert(tostring(err):find("annotate_view.lua", 1, true))
  eq(nil, created)
  vim.env.XDG_CONFIG_HOME = xdg_config_home
  _G.rex = nil
end)

test("unsupported or changed targets never receive input", function()
  for _, case in ipairs({ "unknown", "changed", "unbracketed", "controls" }) do
    local process = { foreground = { pid = 42, path = "/bin/codex", argv0 = "codex" } }
    local original = core.identity(process)
    if case == "unknown" then original = nil end
    if case == "changed" then process.foreground.pid = 43 end
    local sent = false
    local ok = pcall(core.insert, function(method)
      if method == "com.superlogical.terminal.process" then return process end
      if method == "com.superlogical.terminal.modes" then return { modes = { { number = 2004, set = case ~= "unbracketed" } } } end
      sent = true; return {}
    end, { session_id = "session:test", block_id = "block:source" }, original,
      case == "controls" and "hello\27[201~" or "quote\ncomment")
    eq(false, ok)
    eq(false, sent)
  end
end)

test("an ambiguous paste failure is attempted once and propagated", function()
  local process = { foreground = { pid = 42, path = "/bin/codex" } }
  local sent = 0
  local ok = pcall(core.insert, function(method)
    if method == "com.superlogical.terminal.process" then return process end
    if method == "com.superlogical.terminal.modes" then return { modes = { { number = 2004, set = true } } } end
    sent = sent + 1; error("timeout")
  end, { session_id = "s", block_id = "b" }, core.identity(process), "hello")
  eq(false, ok); eq(1, sent)
end)

test("capture refuses oversized, stalled, and changed snapshots", function()
  for _, case in ipairs({ "oversized", "stalled", "changed" }) do
    local calls = 0
    local ok = pcall(core.capture, function()
      calls = calls + 1
      if calls == 1 then return { content = "abc", total = case == "oversized" and 999 or 6, id = 17 } end
      return { id = case == "changed" and 18 or 17, data = "", eof = false }
    end, { session_id = "s", block_id = "b" }, 10)
    eq(false, ok)
    assert(calls <= 2)
  end
end)

test("installed process variants are recognized without reading credentials or arguments", function()
  for _, case in ipairs({
    { "Pi", { pid = 1, path = "/bin/node", argv0 = "pi" } },
    { "Codex", { pid = 2, path = "/opt/codex" } },
    { "Claude Code", { pid = 3, path = "/home/me/.local/share/claude/versions/2.1.322" } },
    { "Claude Code", { pid = 4, path = "/bin/claude" } },
  }) do eq(case[1], core.identity({ foreground = case[2] }).agent) end
  eq(nil, core.identity({ foreground = { pid = 5, path = "/bin/zsh" } }))
end)

test("V, reversed Unicode selection, search, preview, and explicit copy use the same payload", function()
  local view = dofile(root .. "annotate_view.lua")
  local copied = {}
  local session = view.open("é猫 x\nneedle line\nend", { block_id = "b" }, {
    copy = function(payload) copied[#copied + 1] = payload end,
  })
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("lvh" .. vim.keycode("<CR>") .. "unicode" .. vim.keycode("<C-s>"), "xt")
  assert(session:payload():find("> é猫", 1, true))
  vim.fn.feedkeys("/needle" .. vim.keycode("<CR>") .. "V" .. vim.keycode("<CR>") .. "linewise" .. vim.keycode("<C-s>"), "xt")
  assert(session:payload():find("> needle line\n> \n\nComment:\nlinewise", 1, true))
  eq(0, #copied)
  vim.fn.feedkeys("py", "xt")
  eq(session:payload(), table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n"))
  eq({ session:payload() }, copied)
  eq(true, vim.api.nvim_buf_is_valid(session.source)) -- Copy leaves the overlay open.
  session:close(true)
end)

test("canceling a new comment preserves the selection and prior annotations", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha beta", { block_id = "b" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. vim.keycode("<Esc>") .. "q", "xt")
  eq("", session:payload())
  eq("v", vim.fn.mode())
  eq({ 1, 4 }, vim.api.nvim_win_get_cursor(0))
  vim.cmd.normal({ args = { vim.keycode("<Esc>") }, bang = true })
  session:close(true)
end)

test("notes can be edited and removed through the picker without altering quotes", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha beta", { block_id = "b" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "first" .. vim.keycode("<C-s>"), "xt")
  local select = vim.ui.select
  vim.ui.select = function(items, _, callback) callback(items[1]) end
  vim.fn.feedkeys("m" .. vim.keycode("<Esc>") .. "gg0Cupdated" .. vim.keycode("<C-s>"), "xt")
  assert(session:payload():find("> alpha\n\nComment:\nupdated", 1, true))
  vim.ui.select = function(items, _, callback)
    callback(type(items[1]) == "table" and items[1] or items[2])
  end
  vim.fn.feedkeys("m", "xt")
  eq("", session:payload())
  vim.ui.select = select
  session:close(true)
end)

test("discard warning keeps notes open and a failed copy preserves the draft", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha", { block_id = "b" }, { copy = function() error("clipboard unavailable") end })
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "note" .. vim.keycode("<C-s>"), "xt")
  local payload = session:payload()
  vim.fn.feedkeys("y", "xt")
  eq(payload, session:payload())
  local confirm = vim.fn.confirm
  vim.fn.confirm = function() return 1 end
  eq(false, session:close())
  eq(payload, session:payload())
  vim.fn.confirm = function() return 2 end
  eq(true, session:close())
  vim.fn.confirm = confirm
end)

test("first-page truncation without a continuation is refused", function()
  local ok = pcall(core.capture, function() return { content = "abc", total = 6, eof = false } end,
    { session_id = "s", block_id = "b" })
  eq(false, ok)
end)

test("identical quotes on one line retain distinct byte ranges", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("same same", { block_id = "b" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v3l" .. vim.keycode("<CR>") .. "first" .. vim.keycode("<C-s>"), "xt")
  vim.fn.feedkeys("wv3l" .. vim.keycode("<CR>") .. "second" .. vim.keycode("<C-s>"), "xt")
  eq({ 1, 0, 1, 4 }, vim.list_slice(session.draft.notes[1].range, 1, 4))
  eq({ 1, 5, 1, 9 }, vim.list_slice(session.draft.notes[2].range, 1, 4))
  session:close(true)
end)

test("closing a comment window cannot strand the editor or silently lose edits", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha beta", { block_id = "b" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "unsaved" .. vim.keycode("<Esc>"), "xt")
  local closed = pcall(vim.cmd.close)
  eq(false, closed) -- Native close refuses an unsaved comment.
  local confirm = vim.fn.confirm
  vim.fn.confirm = function() return 2 end
  vim.cmd("q!") -- Explicitly discard the comment through the native exit path.
  vim.fn.confirm = confirm
  vim.wait(20, function() return vim.api.nvim_get_current_buf() == session.source end)
  vim.fn.feedkeys("gv" .. vim.keycode("<CR>") .. "later" .. vim.keycode("<C-s>"), "xt")
  assert(session:payload():find("Comment:\nlater", 1, true))
  session:close(true)
end)

test("overlay is centered in the Rex window while retaining nested/floating target dimensions", function()
  local target = { session_id = "s", window_id = "w", block_id = "target" }
  local window = { window_id = "w", layers = {
    { kind = "tiled", layout = { split = {
      before = { block_id = "other", rect = { 0, 0, 0.4, 1 } },
      after = { split = {
        before = { block_id = "above", rect = { 0.4, 0, 0.6, 0.25 } },
        after = { block_id = "target", rect = { 0.4, 0.25, 0.6, 0.75 } },
      } },
    } } },
  } }
  local bounds = core.overlay_bounds({ windows = { { window_id = "unrelated" }, window } }, target)
  for i, expected in ipairs({ 0.2, 0.1625, 0.6, 0.675 }) do assert(math.abs(bounds[i] - expected) < 1e-10) end
  window.layers = { { kind = "floating", bounds = { 0.2, 0.1, 0.45, 0.6 },
    layout = { block_id = "target", rect = { 0.2, 0.1, 0.45, 0.6 } } } }
  bounds = core.overlay_bounds({ windows = { window } }, target)
  for i, expected in ipairs({ 0.275, 0.23, 0.45, 0.54 }) do assert(math.abs(bounds[i] - expected) < 1e-10) end
  window.zoomed_block_id = "target"
  bounds_eq({ 0, 0.05, 1, 0.9 }, core.overlay_bounds({ windows = { window } }, target))
  eq(false, pcall(core.overlay_bounds, { windows = {} }, target))
end)

test("exit restores the captured target only while this overlay and window still have focus", function()
  local target = { session_id = "s", window_id = "w", block_id = "target" }
  local source = { block_id = "target", rect = { 0, 0, 0.375, 1 } }
  local window = { window_id = "w", focused_block_id = "overlay", layers = { { layout = source } } }
  local view = { active_window_id = "w", windows = { window } }
  local focused = {}
  local function call(method, args)
    if method == "session.view" then eq("s", args.session_id); return view end
    eq("session.focus_block", method)
    focused[#focused + 1] = args
    return {}
  end
  eq(true, core.restore_focus(call, target, "overlay"))
  eq({ { session_id = "s", block_id = "target" } }, focused)
  focused = {}
  window.focused_block_id = "other"
  eq(false, core.restore_focus(call, target, "overlay"))
  window.focused_block_id = "overlay"
  view.active_window_id = "another-window"
  eq(false, core.restore_focus(call, target, "overlay"))
  view.active_window_id = "w"
  source.block_id = "replacement"
  eq(false, core.restore_focus(call, target, "overlay"))
  eq({}, focused)
end)

test("copy and insert receive identical multiline Unicode and pipe content", function()
  local view = dofile(root .. "annotate_view.lua")
  local copied, inserted
  local session = view.open("a | b\né猫", { block_id = "b" }, {
    copy = function(value) copied = value end, insert = function(value) inserted = value end,
  })
  vim.fn.feedkeys("gg0Vj" .. vim.keycode("<CR>") .. "note" .. vim.keycode("<CR>") .. "next line" .. vim.keycode("<C-s>"), "xt")
  local confirm = vim.fn.confirm
  vim.fn.confirm = function() return 2 end
  vim.fn.feedkeys("ys", "xt")
  vim.fn.confirm = confirm
  eq(session:payload(), copied); eq(copied, inserted)
  assert(inserted:find("a | b", 1, true) and inserted:find("note\nnext line", 1, true))
  eq(false, vim.api.nvim_buf_is_valid(session.source)) -- Successful insertion auto-closes.
  session:close(true)
end)

print("PASS " .. passed .. " Rex annotation tests")
