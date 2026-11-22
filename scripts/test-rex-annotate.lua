-- Run with: nvim --headless --noplugin -u NONE -i NONE -n -l scripts/test-rex-annotate.lua
local root = vim.fn.getcwd() .. "/rex/"
local core = dofile(root .. "annotate_core.lua")
local passed = 0
local function test(name, run)
  local ok, err = xpcall(run, debug.traceback)
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
  eq("# Terminal annotations\n\n> alpha\n> beta\n\nFeedback: explain", draft:format())
  draft:edit(id, "why?\nplease clarify")
  eq("# Terminal annotations\n\n> alpha\n> beta\n\nFeedback:\n\n~~~\nwhy?\nplease clarify\n~~~", draft:format())
  draft:remove(id)
  eq("", draft:format())
end)

test("compact feedback keeps pairs and internal quote lines without a trailing linewise separator", function()
  local draft = core.draft("source")
  draft:add("é | first\n\n  second\n", "Yes", { mode = "V" })
  draft:add("other", "No\n~~~~\nExplain why", { mode = "v" })
  draft:add("last", "Done", { mode = "v" })
  eq("# Terminal annotations\n\n> é | first\n> \n>   second\n\nFeedback: Yes\n\n> other\n\nFeedback:\n\n~~~~~\nNo\n~~~~\nExplain why\n~~~~~\n\n> last\n\nFeedback: Done",
    draft:format())
  eq("é | first\n\n  second\n", draft.notes[1].quote)
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
  local quits = 0
  local services = { quit = function() quits = quits + 1 end }
  local picker = view.pick_replies({
    { id = "private-old-id", hash = "deadbeef", timestamp = "invalid timestamp", text = "older reply\nsecond line" },
    { id = "private-latest-id", hash = "facefeed", timestamp = os.date("!%Y-%m-%dT%H:%M:%SZ", os.time() - 125),
      text = "latest exact reply\nwith Unicode é and pipes |" },
  }, target, services)
  local lines = vim.api.nvim_buf_get_lines(picker.picker, 0, -1, false)
  eq("    2m  latest exact reply", lines[3])
  eq("     ?  older reply", lines[4])
  assert(not table.concat(lines, "\n"):find("PI REPLIES", 1, true))
  assert(not table.concat(lines, "\n"):find("private-latest-id", 1, true))
  assert(not table.concat(lines, "\n"):find("deadbeef", 1, true))
  assert(not table.concat(lines, "\n"):find("%d%d%d%d%-", 1))
  assert(vim.wo[0].winbar:find("PI REPLIES", 1, true))
  local picker_options = {
    wrap = vim.wo[0].wrap,
    number = vim.wo[0].number,
    cursorline = vim.wo[0].cursorline,
    winbar = vim.wo[0].winbar,
    statusline = vim.wo[0].statusline,
  }
  local selected_cursor = vim.api.nvim_win_get_cursor(0)
  vim.fn.feedkeys(vim.keycode("<CR>"), "xt")
  local session = picker.editor
  assert(session)
  eq({ "latest exact reply", "with Unicode é and pipes |" }, vim.api.nvim_buf_get_lines(session.source, 0, -1, false))
  eq(true, vim.wo[0].wrap)
  vim.fn.feedkeys(vim.keycode("<C-w>"), "xt")
  eq(false, vim.wo[0].wrap)
  assert(vim.wo[0].statusline:find("nowrap", 1, true))
  vim.fn.feedkeys(vim.keycode("<C-w>"), "xt")
  eq(true, vim.wo[0].wrap)
  assert(vim.wo[0].statusline:find(" · wrap ", 1, true))
  local help
  for _, window in ipairs(vim.api.nvim_tabpage_list_wins(0)) do
    local help_buf = vim.api.nvim_win_get_buf(window)
    if help_buf ~= session.source and help_buf ~= picker.picker then
      help = table.concat(vim.api.nvim_buf_get_lines(help_buf, 0, -1, false), "\n")
    end
  end
  assert(help and help:find("Esc list", 1, true))
  assert(help:find("Ctrl+W wrap", 1, true))
  local back = vim.fn.maparg("<Esc>", "n", false, true)
  eq(1, back.buffer)
  assert(type(back.callback) == "function")

  vim.fn.feedkeys(vim.keycode("<Esc>"), "xt")
  eq(picker.picker, vim.api.nvim_get_current_buf())
  eq(selected_cursor, vim.api.nvim_win_get_cursor(0))
  eq(picker_options.wrap, vim.wo[0].wrap)
  eq(picker_options.number, vim.wo[0].number)
  eq(picker_options.cursorline, vim.wo[0].cursorline)
  eq(picker_options.winbar, vim.wo[0].winbar)
  eq(picker_options.statusline, vim.wo[0].statusline)
  eq(false, vim.api.nvim_buf_is_valid(session.source))
  eq(0, quits)
  vim.fn.feedkeys("q", "xt")
  eq(1, quits)
  vim.api.nvim_buf_delete(picker.picker, { force = true })
end)

test("last-opened reply is per conversation and frozen until the picker is reopened", function()
  local view = dofile(root .. "annotate_view.lua")
  local state = vim.fn.tempname()
  local function open(agent, conversation, ids)
    local replies = vim.tbl_map(function(id) return { id = id, text = "Reply " .. id } end, ids)
    return view.pick_replies(replies, { block_id = "b" }, {}, agent, conversation, state)
  end
  local function markers(picker)
    local namespace = vim.api.nvim_create_namespace("rex-annotate-picker-last-opened")
    return vim.tbl_map(function(mark)
      eq(true, mark[4].virt_lines_above)
      eq("── Last opened ──", mark[4].virt_lines[1][1][1])
      return vim.api.nvim_buf_get_lines(picker.picker, mark[2], mark[2] + 1, false)[1]
    end, vim.api.nvim_buf_get_extmarks(picker.picker, namespace, 0, -1, { details = true }))
  end
  local function close(picker) vim.api.nvim_buf_delete(picker.picker, { force = true }) end
  local ok, err = pcall(function()
    local picker = open("Pi", "thread", { "A", "B" })
    eq({}, markers(picker))
    close(picker)
    picker = open("Pi", "thread", { "A", "B", "C", "D" })
    eq({ "     ?  Reply B" }, markers(picker))
    eq(6, vim.api.nvim_buf_line_count(picker.picker))
    for _, row in ipairs({ 3, 6, 5 }) do
      assert(picker.select(row):close(false, true))
      eq({ "     ?  Reply B" }, markers(picker))
    end
    close(picker)
    picker = open("Pi", "thread", { "A", "B", "C", "D" })
    eq({ "     ?  Reply D" }, markers(picker))
    close(picker)
    for _, scope in ipairs({ {"Pi", "other"}, {"Codex", "thread"}, {"Pi", "thread"} }) do
      picker = open(scope[1], scope[2], { "A", "B" })
      eq({}, markers(picker)) -- Other conversations/agents and absent replies never match.
      close(picker)
    end
  end)
  vim.fn.delete(state, "rf")
  assert(ok, err)
end)

test("notes across replies survive Back and preview and insert as one draft", function()
  local view = dofile(root .. "annotate_view.lua")
  local quits, inserted = 0, nil
  local picker = view.pick_replies({ { text = "older" }, { text = "newest" } },
    { block_id = "b" }, {
      insert_requires_confirmation = false,
      insert = function(payload) inserted = payload end,
      quit = function() quits = quits + 1 end,
    })
  local function note_marks()
    local ns = vim.api.nvim_get_namespaces()["rex-annotate-picker-notes"]
    return vim.tbl_map(function(mark) return { mark[2], mark[4].virt_text[1][1] } end,
      vim.api.nvim_buf_get_extmarks(picker.picker, ns, 0, -1, { details = true }))
  end
  eq({}, note_marks())
  local older = picker.select(4)
  local range = { 1, 0, 1, 5, mode = "v" }
  local id = older.draft:add("older", "second", range)
  local extra = older.draft:add("older", "extra", range)
  assert(older:close(false, true))
  eq({ { 3, "[2 notes] " } }, note_marks())
  vim.api.nvim_win_set_cursor(0, { 4, 0 })
  vim.fn.feedkeys("m", "xt")
  local manager = vim.api.nvim_get_current_buf()
  eq({ "Reply 2 · [" .. id .. "] L1:1  second", "Reply 2 · [" .. extra .. "] L1:1  extra" },
    vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys("jxxq", "xt")
  eq(picker.picker, vim.api.nvim_get_current_buf())
  eq(false, vim.api.nvim_buf_is_valid(manager))
  eq({ 4, 0 }, vim.api.nvim_win_get_cursor(0))
  eq({ { 3, "[1 note] " } }, note_marks())
  assert(vim.wo[0].statusline:find("1 note ·", 1, true))
  vim.fn.feedkeys("m" .. vim.keycode("<CR>"), "xt")
  eq({ "second" }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys(vim.keycode("<CR>"), "xt")
  eq({ "Reply 2 · [" .. id .. "] L1:1  second" }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys("xxq", "xt")
  eq(picker.picker, vim.api.nvim_get_current_buf())
  eq({}, note_marks())
  older = picker.select(4)
  older.draft:add("older", "second", range)
  assert(older:close(false, true))
  local newest = picker.select(3)
  eq(0, #newest.draft.notes)
  newest.draft:add("newest", "first", { 1, 0, 1, 6, mode = "v" })
  assert(newest:close(false, true))
  eq({ { 2, "[1 note] " }, { 3, "[1 note] " } }, note_marks())
  vim.api.nvim_win_set_cursor(0, { 3, 0 })
  vim.fn.feedkeys("m", "xt")
  eq({ "Reply 1 · [1] L1:1  first", "Reply 2 · [3] L1:1  second" },
    vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys("j" .. vim.keycode("<CR><Esc>") .. "gg0Cedited" .. vim.keycode("<CR>") .. "q", "xt")
  eq({ 3, 0 }, vim.api.nvim_win_get_cursor(0))
  eq(picker.picker, vim.api.nvim_get_current_buf())

  local original_confirm = vim.fn.confirm
  vim.fn.confirm = function(message) eq("Discard unfinished annotations?", message); return 1 end
  local quit = vim.api.nvim_get_autocmds({ event = "QuitPre", buffer = picker.picker })[1]
  local ok, err = pcall(quit.callback)
  vim.fn.confirm = original_confirm
  assert(not ok and tostring(err):find("Annotations kept open", 1, true))

  local payload = "# Terminal annotations\n\n## Reply 1\n\n> newest\n\nFeedback: first"
    .. "\n\n## Reply 2\n\n> older\n\nFeedback: edited"
  local cursor = vim.api.nvim_win_get_cursor(0)
  vim.fn.feedkeys("p", "xt")
  eq(payload, table.concat(vim.api.nvim_buf_get_lines(0, 0, -1, false), "\n"))
  vim.fn.feedkeys(vim.keycode("<Esc>"), "xt")
  eq(picker.picker, vim.api.nvim_get_current_buf())
  eq(cursor, vim.api.nvim_win_get_cursor(0))
  vim.fn.feedkeys("p", "xt")
  local preview = vim.api.nvim_get_current_buf()
  vim.fn.feedkeys(vim.keycode("<S-CR>"), "xt")
  eq(payload, inserted)
  eq(1, quits)
  vim.api.nvim_buf_delete(preview, { force = true })
  vim.api.nvim_buf_delete(picker.picker, { force = true })
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
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "comment" .. vim.keycode("<CR>"), "xt")
  local input = vim.fn.input
  vim.fn.input = function() error("Send must not request typed confirmation") end
  vim.fn.feedkeys(vim.keycode("<C-CR>"), "xt")
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
  local ok, err = pcall(vim.fn.feedkeys, "v4l" .. vim.keycode("<CR>") .. "why" .. vim.keycode("<CR>") .. vim.keycode("<S-CR>"), "xt")
  vim.fn.confirm = confirm
  assert(ok, err)
  assert(inserted:find("Feedback: why", 1, true))
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
  vim.fn.feedkeys(vim.keycode("<S-CR><C-CR>"), "xt")
  eq(payload, session:payload())
  eq(true, vim.api.nvim_buf_is_valid(session.source))
  eq(0, quit)
  session:close(true)
end)

test("busy Pi leaves a retry hint without a hit-enter prompt and allows a manual retry", function()
  local view = dofile(root .. "annotate_view.lua")
  local attempts, quit = 0, 0
  local session = view.open("alpha", { block_id = "b" }, {
    insert_requires_confirmation = false,
    insert = function()
      attempts = attempts + 1
      if attempts == 1 then error("Pi is busy; wait for its editable prompt") end
    end,
    quit = function() quit = quit + 1 end,
  })
  session.draft:add("alpha", "keep this note", { 1, 0, 1, 5 })
  local payload = session:payload()
  vim.fn.feedkeys("p" .. vim.keycode("<S-CR>"), "xt")
  eq(1, attempts)
  eq(0, quit)
  eq(payload, session:payload())
  assert(vim.wo.statusline:find("Pi busy. Notes kept; retry when idle.", 1, true))
  assert(not vim.wo.statusline:find(".lua", 1, true))
  vim.fn.feedkeys(vim.keycode("<S-CR>"), "xt")
  eq(2, attempts)
  eq(1, quit)
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
  local ok, err = pcall(vim.fn.feedkeys, vim.keycode("<S-CR>"), "xt")
  vim.fn.confirm = confirm
  assert(ok, err)
  eq(1, calls)
  eq(nil, inserted)
  assert(session:payload():find("Feedback: note", 1, true))
  session:close(true)
end)

test("Vim selection attaches the exact quote and multiline comment in the view", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha beta\ngamma delta", { session_id = "session:test", block_id = "block:source" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  -- Exercise selection, the real comment editor, and its save mapping in one input stream.
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "why?" .. vim.keycode("<S-CR>") .. "clarify" .. vim.keycode("<CR>"), "xt")
  eq("# Terminal annotations\n\n> alpha\n\nFeedback:\n\n~~~\nwhy?\nclarify\n~~~", session:payload())
  session:close(true)
end)

test("Markdown styling preserves reply bytes and fenced code takes precedence", function()
  local view = dofile(root .. "annotate_view.lua")
  local snapshot = "# Élan\n- bullet\n> quote\n````lua\n# not a heading\n```\n````\n## Back"
  local session = view.open(snapshot, { block_id = "b" }, {}, "REPLY", function() return true end)
  local ns = vim.api.nvim_get_namespaces()["rex-annotate-markdown"]
  local marks = {}
  for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(session.source, ns, 0, -1, { details = true })) do
    local row, style = mark[2] + 1, mark[4].hl_group or mark[4].line_hl_group
    marks[row] = marks[row] or {}
    marks[row][style] = true
  end
  assert(marks[1].RexMarkdownHeading and marks[2].RexMarkdownMarker and marks[3].RexMarkdownQuote)
  assert(marks[5].RexMarkdownCode and not marks[5].RexMarkdownHeading)
  assert(marks[6].RexMarkdownCode and not marks[6].RexMarkdownMarker)
  assert(marks[8].RexMarkdownHeading)
  vim.fn.feedkeys("ggV" .. vim.keycode("<CR><C-y>"), "xt")
  assert(session:payload():find("> # Élan", 1, true))
  eq(snapshot, table.concat(vim.api.nvim_buf_get_lines(session.source, 0, -1, false), "\n"))
  session:close(true)
end)

test("Markdown reply decorates inline links, code, and tables without changing quotes", function()
  local view = dofile(root .. "annotate_view.lua")
  local first = "**[Rex](https://example.com/) avec `é猫`**"
  local snapshot = first .. "\n\n| Key | Action |\n| --- | --- |\n| `Enter` | Save |"
  local session = view.open(snapshot, { block_id = "b" }, {}, "REPLY", function() return true end)
  local ns = vim.api.nvim_get_namespaces()["rex-annotate-markdown"]
  local styles, hidden, aligned = {}, 0, false
  for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(session.source, ns, 0, -1, { details = true })) do
    local details = mark[4]
    if mark[2] == 0 then
      styles[details.hl_group] = true
      if details.conceal ~= nil then hidden = hidden + 1 end
    elseif details.virt_text_pos == "inline" then aligned = true end
  end
  assert(styles.RexMarkdownLink and styles.RexMarkdownHeading and styles.RexMarkdownInlineCode)
  assert(hidden >= 6 and aligned)
  eq(2, vim.wo.conceallevel)
  vim.fn.feedkeys("ggV" .. vim.keycode("<CR><C-y>"), "xt")
  assert(session:payload():find(first, 1, true))
  eq(snapshot, table.concat(vim.api.nvim_buf_get_lines(session.source, 0, -1, false), "\n"))
  session:close(true)
end)

test("annotated spans use exact UTF-8 byte ranges and linewise ranges include newline", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("é猫 tail\nsecond\nlast", { block_id = "b" }, {})
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("vl" .. vim.keycode("<CR>") .. "unicode" .. vim.keycode("<CR>"), "xt")
  eq({ 1, 0, 1, 5 }, vim.list_slice(session.draft.notes[1].range, 1, 4))
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  vim.fn.feedkeys("V" .. vim.keycode("<CR>") .. "linewise" .. vim.keycode("<CR>"), "xt")
  eq({ 2, 0, 3, 0 }, vim.list_slice(session.draft.notes[2].range, 1, 4))
  assert(session:payload():find("> second\n\nFeedback: linewise", 1, true))
  local spans = {}
  for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(session.source, session.namespace, 0, -1, { details = true })) do
    if mark[4].hl_group then spans[#spans + 1] = mark end
  end
  eq(2, #spans)
  eq({ 0, 0, 0, 5, "RexAnnotationComment" }, { spans[1][2], spans[1][3], spans[1][4].end_row,
    spans[1][4].end_col, spans[1][4].hl_group })
  eq({ 1, 0, 2, 0, "RexAnnotationComment" }, { spans[2][2], spans[2][3], spans[2][4].end_row,
    spans[2][4].end_col, spans[2][4].hl_group })
  session:close(true)
end)

test("comment displays the exact read-only quote and saves Yes or No without delivery", function()
  local view = dofile(root .. "annotate_view.lua")
  local deliveries = 0
  local function deliver() deliveries = deliveries + 1 end
  local session = view.open("é猫 tail\nsecond\nthird\nfourth\nfifth", { block_id = "b" },
    { copy = deliver, insert = deliver, send = deliver })
  local base_windows = #vim.api.nvim_list_wins()
  vim.fn.feedkeys("ggVjjjj" .. vim.keycode("<CR><Esc>"), "xt")
  local modal, quote, quote_win = vim.api.nvim_get_current_win()
  for _, candidate in ipairs(vim.api.nvim_list_wins()) do
    if vim.api.nvim_win_get_config(candidate).relative ~= "" and candidate ~= modal then
      quote, quote_win = vim.api.nvim_win_get_buf(candidate), candidate
    end
  end
  assert(quote)
  eq({ "é猫 tail", "second", "third", "fourth", "fifth" }, vim.api.nvim_buf_get_lines(quote, 0, -1, false))
  eq(false, vim.bo[quote].modifiable)
  eq({ "" }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  local width, height = vim.o.columns, vim.o.lines
  vim.o.columns, vim.o.lines = 34, 16
  vim.api.nvim_exec_autocmds("VimResized", {})
  eq(30, vim.api.nvim_win_get_width(modal))
  eq(30, vim.api.nvim_win_get_width(quote_win))
  local function topline() return vim.api.nvim_win_call(quote_win, function() return vim.fn.line("w0") end) end
  eq(1, topline())
  vim.fn.feedkeys(vim.keycode("<PageDown>"), "xt")
  assert(topline() > 1, "quote must scroll independently")
  eq(modal, vim.api.nvim_get_current_win())
  vim.o.columns, vim.o.lines = width, height
  vim.api.nvim_exec_autocmds("VimResized", {})
  vim.fn.feedkeys(vim.keycode("<C-y>"), "xt")
  eq(base_windows, #vim.api.nvim_list_wins())
  eq(false, vim.api.nvim_buf_is_valid(quote))
  vim.fn.feedkeys("ggvl" .. vim.keycode("<CR><C-n>"), "xt")
  assert(session:payload():find("Feedback: Yes", 1, true))
  assert(session:payload():find("> é猫\n\nFeedback: No", 1, true))
  eq(0, deliveries)
  session:close(true)
end)

test("jump follows document order, wraps, and edits the jumped note even at a shared start", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("αβ gamma\nmiddle\nlast", { block_id = "b" }, {})
  vim.fn.feedkeys("G" .. vim.keycode("<CR><C-y>"), "xt")
  vim.fn.feedkeys("ggvl" .. vim.keycode("<CR><C-n>"), "xt")
  vim.fn.feedkeys("ggvwl" .. vim.keycode("<CR><C-y>"), "xt")
  vim.fn.feedkeys("G0N", "xt")
  eq({ 1, 0 }, vim.api.nvim_win_get_cursor(0))
  vim.fn.feedkeys(vim.keycode("<C-e>") .. vim.keycode("<Esc>"), "xt")
  eq({ "Yes" }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys("0Cchanged" .. vim.keycode("<CR>"), "xt")
  vim.fn.feedkeys("N", "xt")
  eq({ 1, 0 }, vim.api.nvim_win_get_cursor(0))
  vim.fn.feedkeys(vim.keycode("<C-e>") .. vim.keycode("<Esc>"), "xt")
  eq({ "No" }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys("qN", "xt")
  eq({ 3, 0 }, vim.api.nvim_win_get_cursor(0))
  vim.fn.feedkeys("n", "xt")
  eq({ 1, 0 }, vim.api.nvim_win_get_cursor(0))
  assert(session:payload():find("Feedback: changed", 1, true))
  local base_windows = #vim.api.nvim_list_wins()
  vim.fn.feedkeys(vim.keycode("<C-e>") .. vim.keycode("<Esc>"), "xt")
  eq(base_windows + 2, #vim.api.nvim_list_wins())
  session:close(true)
  eq(base_windows - 1, #vim.api.nvim_list_wins())
end)

test("note colors pair each quote and label, update on edit, and leave Visual alone", function()
  local view = dofile(root .. "annotate_view.lua")
  local visual = vim.api.nvim_get_hl(0, { name = "Visual", link = false })
  local snapshot = "one\ntwo\nthree"
  local session = view.open(snapshot, { block_id = "palette-test" }, {})
  vim.fn.feedkeys("gg0" .. vim.keycode("<CR><C-y>") .. "j" .. vim.keycode("<CR><C-n>")
    .. "j" .. vim.keycode("<CR>") .. "Yes, explain why" .. vim.keycode("<CR>"), "xt")
  local function groups()
    local spans, labels = {}, {}
    for _, mark in ipairs(vim.api.nvim_buf_get_extmarks(session.source, session.namespace, 0, -1, { details = true })) do
      if mark[4].hl_group then spans[#spans + 1] = mark[4].hl_group end
      if mark[4].virt_text then labels[#labels + 1] = mark[4].virt_text[1][2] end
    end
    eq(spans, labels)
    return spans
  end
  eq({ "RexAnnotationYes", "RexAnnotationNo", "RexAnnotationComment" }, groups())
  local original = vim.o.background
  for _, theme in ipairs({ "dark", "light" }) do
    vim.o.background = theme
    vim.api.nvim_exec_autocmds("OptionSet", { pattern = "background" })
    local colors = {}
    for _, name in ipairs(groups()) do
      local style = vim.api.nvim_get_hl(0, { name = name })
      assert(style.fg and style.bg and style.ctermfg and style.ctermbg)
      assert(not colors[style.bg], "each note type has its own color")
      colors[style.bg] = true
    end
  end
  vim.o.background = original
  vim.fn.feedkeys("gg0" .. vim.keycode("<C-e>") .. vim.keycode("<C-n>"), "xt")
  eq({ "RexAnnotationNo", "RexAnnotationNo", "RexAnnotationComment" }, groups())
  eq(visual, vim.api.nvim_get_hl(0, { name = "Visual", link = false }))
  eq(snapshot, table.concat(vim.api.nvim_buf_get_lines(session.source, 0, -1, false), "\n"))
  session:close(true)
end)

test("detail keeps native forward and backward search on the backslash shortcuts", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("start\nhit\nhit\nhit", { block_id = "b" }, {})
  vim.fn.feedkeys("gg0/hit" .. vim.keycode("<CR>"), "xt")
  eq({ 2, 0 }, vim.api.nvim_win_get_cursor(0))
  vim.fn.feedkeys("2\\n", "xt")
  eq({ 4, 0 }, vim.api.nvim_win_get_cursor(0))
  vim.fn.feedkeys("\\N", "xt")
  eq({ 3, 0 }, vim.api.nvim_win_get_cursor(0))
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
    for _, help in ipairs({ "v/V select", "Enter note", "n/N notes", "\\n/\\N search", "Ctrl+E edit", "m manage", "p preview", "y copy", "Shift+Enter insert", "Ctrl+Enter send", "Ctrl+W wrap", "q close" }) do
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
  for _, action in ipairs({ "v/V select", "Enter note", "n/N notes", "\\n/\\N search", "Ctrl+E edit", "m manage", "p preview", "y copy", "Shift+Enter insert", "Ctrl+Enter send", "q close" }) do
    assert(help:find(action, 1, true), action)
  end
  assert(vim.wo[0].statusline:find("block%%source", 1, true))
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  vim.fn.feedkeys(vim.keycode("<CR>") .. "explain" .. vim.keycode("<CR>"), "xt")
  eq("current line\n", session.draft.notes[1].quote)
  eq({ 2, 0, 3, 0 }, vim.list_slice(session.draft.notes[1].range, 1, 4))
  session:close(true)
end)

test("normal Ctrl+Y and Ctrl+N save current-line notes without opening the editor or delivering", function()
  local view = dofile(root .. "annotate_view.lua")
  local deliveries = 0
  local function deliver() deliveries = deliveries + 1 end
  local session = view.open("café\nlast", { block_id = "b" }, { copy = deliver, insert = deliver, send = deliver })
  vim.fn.feedkeys(vim.keycode("<C-y>"), "xt")
  eq(session.source, vim.api.nvim_get_current_buf())
  eq("café\n", session.draft.notes[1].quote)
  eq("Yes", session.draft.notes[1].comment)
  eq({ 1, 0, 2, 0, mode = "V" }, session.draft.notes[1].range)
  vim.api.nvim_win_set_cursor(0, { 2, 2 })
  vim.fn.feedkeys(vim.keycode("<C-n>"), "xt")
  eq(session.source, vim.api.nvim_get_current_buf())
  eq("last", session.draft.notes[2].quote)
  eq("No", session.draft.notes[2].comment)
  eq({ 2, 0, 2, 4, mode = "V" }, session.draft.notes[2].range)
  eq(0, deliveries)
  session:close(true)
end)

test("x confirms removal of the newest note on the current logical line", function()
  local view = dofile(root .. "annotate_view.lua")
  local quits = 0
  local session = view.open("alpha\nbeta\ngamma", { block_id = "b" }, { quit = function() quits = quits + 1 end })
  session.draft:add("alpha\nbeta\n", "older", { 1, 0, 3, 0, mode = "V" })
  session.draft:add("be", "newest", { 2, 0, 2, 2, mode = "v" })
  vim.api.nvim_win_set_cursor(0, { 2, 3 })
  for _, key in ipairs({ "q", vim.keycode("<Esc>") }) do
    vim.fn.feedkeys("x" .. key, "xt")
    eq(2, #session.draft.notes)
    eq(0, quits)
  end
  vim.fn.feedkeys("xx", "xt")
  eq(1, #session.draft.notes)
  eq("older", session.draft.notes[1].comment)
  vim.api.nvim_win_set_cursor(0, { 3, 0 })
  vim.fn.feedkeys("x", "xt")
  eq(1, #session.draft.notes) -- Exclusive linewise endpoint does not count.
  vim.api.nvim_win_set_cursor(0, { 2, 0 })
  vim.fn.feedkeys("xx", "xt")
  eq(0, #session.draft.notes)
  eq(0, quits)
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
  eq(nil, bindings["ctrl+s>shift+o"])
  eq(nil, bindings["ctrl+s>shift+a"])
  eq(nil, bindings["ctrl+s>a"])
  action.run({ session_id = "session:test", block_id = "block:source", client_id = "client:local" }, {})
  eq("window:source", created.window_id)
  eq("session:test", created.session_id)
  bounds_eq({ 0.40625, 0.05, 0.1875, 0.9 }, created.bounds)
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
  vim.fn.feedkeys("lvh" .. vim.keycode("<CR>") .. "unicode" .. vim.keycode("<CR>"), "xt")
  assert(session:payload():find("> é猫", 1, true))
  vim.fn.feedkeys("/needle" .. vim.keycode("<CR>") .. "V" .. vim.keycode("<CR>") .. "linewise" .. vim.keycode("<CR>"), "xt")
  assert(session:payload():find("> needle line\n\nFeedback: linewise", 1, true))
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
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "first" .. vim.keycode("<CR>"), "xt")
  local cursor = vim.api.nvim_win_get_cursor(0)
  vim.fn.feedkeys("m" .. vim.keycode("<CR><Esc>") .. "gg0Cupdated" .. vim.keycode("<CR>"), "xt")
  assert(session:payload():find("> alpha\n\nFeedback: updated", 1, true))
  eq({ "[1] L1:1  updated" }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys("xq", "xt")
  eq(1, #session.draft.notes)
  vim.fn.feedkeys("xx", "xt")
  eq("", session:payload())
  eq({ "No annotations left. Press q or Esc to go back." }, vim.api.nvim_buf_get_lines(0, 0, -1, false))
  vim.fn.feedkeys(vim.keycode("<Esc>"), "xt")
  eq(session.source, vim.api.nvim_get_current_buf())
  eq(cursor, vim.api.nvim_win_get_cursor(0))
  session:close(true)
end)

test("discard warning keeps notes open and a failed copy preserves the draft", function()
  local view = dofile(root .. "annotate_view.lua")
  local session = view.open("alpha", { block_id = "b" }, { copy = function() error("clipboard unavailable") end })
  vim.api.nvim_win_set_cursor(0, { 1, 0 })
  vim.fn.feedkeys("v4l" .. vim.keycode("<CR>") .. "note" .. vim.keycode("<CR>"), "xt")
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
  vim.fn.feedkeys("v3l" .. vim.keycode("<CR>") .. "first" .. vim.keycode("<CR>"), "xt")
  vim.fn.feedkeys("wv3l" .. vim.keycode("<CR>") .. "second" .. vim.keycode("<CR>"), "xt")
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
  vim.fn.feedkeys("gv" .. vim.keycode("<CR>") .. "later" .. vim.keycode("<CR>"), "xt")
  assert(session:payload():find("Feedback: later", 1, true))
  session:close(true)
end)

test("overlay is centered at half the width of nested, floating, or zoomed sources", function()
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
  for i, expected in ipairs({ 0.35, 0.1625, 0.3, 0.675 }) do assert(math.abs(bounds[i] - expected) < 1e-10) end
  window.layers = { { kind = "floating", bounds = { 0.2, 0.1, 0.45, 0.6 },
    layout = { block_id = "target", rect = { 0.2, 0.1, 0.45, 0.6 } } } }
  bounds = core.overlay_bounds({ windows = { window } }, target)
  for i, expected in ipairs({ 0.3875, 0.23, 0.225, 0.54 }) do assert(math.abs(bounds[i] - expected) < 1e-10) end
  window.zoomed_block_id = "target"
  bounds_eq({ 0.25, 0.05, 0.5, 0.9 }, core.overlay_bounds({ windows = { window } }, target))
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
  vim.fn.feedkeys("gg0Vj" .. vim.keycode("<CR>") .. "note" .. vim.keycode("<S-CR>") .. "next line" .. vim.keycode("<CR>"), "xt")
  local confirm = vim.fn.confirm
  vim.fn.confirm = function() return 2 end
  vim.fn.feedkeys("y" .. vim.keycode("<S-CR>"), "xt")
  vim.fn.confirm = confirm
  eq(session:payload(), copied); eq(copied, inserted)
  assert(inserted:find("a | b", 1, true) and inserted:find("note\nnext line", 1, true))
  eq(false, vim.api.nvim_buf_is_valid(session.source)) -- Successful insertion auto-closes.
  session:close(true)
end)

test("startup failure displays multiline actionable errors without a scratch-buffer crash", function()
  local view = dofile(root .. "annotate_view.lua")
  local system = vim.system
  vim.system = function() return { wait = function() return { code = 1, stderr = "underlying failure\ntrace detail" } end } end
  local ok, err = pcall(view.start, { session_id = "session:test", block_id = "block:source" })
  vim.system = system
  assert(ok, err)
  local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
  eq("Rex Annotate could not open:", lines[1])
  local displayed = table.concat(lines, "\n")
  assert(displayed:find("underlying failure", 1, true), vim.inspect(lines))
  assert(displayed:find("trace detail", 1, true), "remaining error lines were lost: " .. vim.inspect(lines))
  eq("Press q to close. No input was sent.", lines[#lines])
  assert(not displayed:find("replacement string", 1, true), displayed)
  local quit = vim.fn.maparg("q", "n", false, true)
  eq(1, quit.buffer)
  assert(type(quit.callback) == "function")
end)

print("PASS " .. passed .. " Rex annotation tests")
