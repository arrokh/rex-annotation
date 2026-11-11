-- A private Neovim view: reuse Vim motions/visual/search; only annotation glue lives here.
local directory = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local core = dofile(directory .. "annotate_core.lua")
local M = {}

local function scratch(lines, editable)
  local buf = vim.api.nvim_create_buf(false, true)
  vim.bo[buf].swapfile = false
  vim.bo[buf].undofile = false
  vim.bo[buf].undolevels = -1
  vim.bo[buf].modeline = false
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = editable == true
  return buf
end

local function mapping(buf, mode, key, fn)
  vim.keymap.set(mode, key, fn, { buffer = buf, silent = true, nowait = true })
end

local function notify(message)
  vim.notify(tostring(message), vim.log.levels.WARN, { title = "Rex Annotate" })
end

local function statusline_text(value)
  local escaped = tostring(value):gsub("%%", "%%%%")
  return escaped
end

local function guarded(fn)
  return function(...)
    local ok, err = pcall(fn, ...)
    if not ok then notify(err) end
  end
end

function M.open(snapshot, target, services, source_title)
  vim.o.modeline = false
  vim.o.shada = ""
  vim.o.backup = false
  vim.o.writebackup = false
  vim.o.clipboard = ""
  vim.o.mouse = ""
  -- Saved marks must remain obvious without sharing the active Visual selection color.
  local annotation_style = { fg = "#1b1b1b", bg = "#f5c542", bold = true, ctermfg = 0, ctermbg = 11 }
  vim.api.nvim_set_hl(0, "RexAnnotationSpan", annotation_style)
  vim.api.nvim_set_hl(0, "RexAnnotationNote", annotation_style)
  local lines = vim.split(snapshot, "\n", { plain = true })
  local source = scratch(lines)
  local win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(win, source)
  -- Keep help in an owned split: winbar truncates long detail titles and cannot reflow.
  vim.cmd("aboveleft 1new")
  local header_win = vim.api.nvim_get_current_win()
  local header = scratch({ "" })
  vim.api.nvim_win_set_buf(header_win, header)
  vim.wo[header_win].winbar = ""
  vim.wo[header_win].statusline = " "
  vim.wo[header_win].cursorline = false
  vim.wo[header_win].number = false
  vim.wo[header_win].relativenumber = false
  vim.wo[header_win].wrap = false
  vim.wo[header_win].winfixheight = true
  vim.api.nvim_set_current_win(win)
  vim.wo[win].wrap = true
  vim.wo[win].number = true
  vim.wo[win].cursorline = true
  local ns = vim.api.nvim_create_namespace("rex-annotate")
  local draft = core.draft(target.block_id)
  local session = { source = source, draft = draft, namespace = ns }
  local group = vim.api.nvim_create_augroup("rex-annotate-" .. source, { clear = true })
  local editor, preview
  local closed = false
  local function wrap_cells(text, width)
    local result, line = {}, ""
    for index = 0, vim.fn.strchars(text) - 1 do
      local char = vim.fn.strcharpart(text, index, 1)
      if line ~= "" and vim.fn.strdisplaywidth(line .. char) > width then
        result[#result + 1], line = line, ""
      end
      line = line .. char
    end
    result[#result + 1] = line
    return result
  end
  local function refresh_header()
    if closed or not vim.api.nvim_win_is_valid(header_win) or not vim.api.nvim_win_is_valid(win) then return end
    local width = math.max(1, vim.api.nvim_win_get_width(header_win))
    local help = wrap_cells(tostring(source_title or "SNAPSHOT"), width)
    local line = ""
    for _, action in ipairs({ "v/V select", "Enter note", "m edit", "p preview", "y copy", "s insert", "S send now", "q close" }) do
      local candidate = line == "" and action or (line .. " · " .. action)
      if vim.fn.strdisplaywidth(candidate) <= width then
        line = candidate
      else
        if line ~= "" then help[#help + 1] = line end
        local parts = wrap_cells(action, width)
        for index = 1, #parts - 1 do help[#help + 1] = parts[index] end
        line = parts[#parts]
      end
    end
    if line ~= "" then help[#help + 1] = line end
    vim.bo[header].modifiable = true
    vim.api.nvim_buf_set_lines(header, 0, -1, false, help)
    vim.bo[header].modifiable = false
    local available = vim.api.nvim_win_get_height(win) + vim.api.nvim_win_get_height(header_win)
    local height = math.min(#help, math.max(1, available - 3))
    if vim.api.nvim_win_get_height(header_win) ~= height then vim.api.nvim_win_set_height(header_win, height) end
    vim.api.nvim_win_set_cursor(header_win, { 1, 0 })
  end
  vim.api.nvim_create_autocmd({ "VimResized", "WinResized" }, { group = group, callback = refresh_header })
  local function refresh()
    vim.api.nvim_buf_clear_namespace(source, ns, 0, -1)
    for _, note in ipairs(draft.notes) do
      local start_row, start_col = note.range[1] - 1, note.range[2]
      local end_row, end_col = note.range[3] - 1, note.range[4]
      vim.api.nvim_buf_set_extmark(source, ns, start_row, start_col, {
        end_row = end_row, end_col = end_col, hl_group = "RexAnnotationSpan", priority = 120,
      })
      local label_row, label_col = end_row, end_col
      if note.range.mode == "V" and end_col == 0 and end_row > start_row then
        label_row = end_row - 1
        label_col = #lines[label_row + 1]
      end
      vim.api.nvim_buf_set_extmark(source, ns, label_row, label_col, {
        virt_text = { { "  [" .. note.id .. "] " .. vim.fn.strcharpart(note.comment:gsub("\n", " "), 0, 70), "RexAnnotationNote" } },
        virt_text_pos = "eol",
      })
    end
    vim.wo[win].winbar = ""
    refresh_header()
    vim.wo[win].statusline = " Rex Annotate · " .. #draft.notes .. " notes · " .. statusline_text(target.block_id) .. " %=%l:%c "
  end
  local function discard(message)
    return vim.fn.confirm(message, "&Keep editing\n&Discard", 1) == 2
  end
  function session:payload() return draft:format() end
  function session:close(force)
    if closed then return true end
    if not force and (draft.dirty or editor) and not discard("Discard unfinished annotations?") then return false end
    closed = true
    vim.api.nvim_del_augroup_by_id(group)
    if vim.api.nvim_win_is_valid(win) and vim.api.nvim_buf_is_valid(source) then
      vim.api.nvim_win_set_buf(win, source)
    end
    if vim.api.nvim_win_is_valid(header_win) then vim.api.nvim_win_close(header_win, true) end
    for _, buf in ipairs({ editor or false, preview or false, header, source }) do
      if buf and vim.api.nvim_buf_is_valid(buf) then vim.api.nvim_buf_delete(buf, { force = true }) end
    end
    if services.quit then services.quit() end
    return true
  end
  local function deliver(kind)
    local payload = draft:format()
    assert(payload ~= "", "Add an annotation first")
    if kind == "copy" then
      assert(services.copy, "Clipboard is unavailable")
      services.copy(payload)
      draft.dirty = false
      notify("Copied annotations")
      return
    elseif kind == "send" then
      assert(services.send, "Explicit Send is unavailable; copy or insert instead")
      services.send(payload)
      draft.notes, draft.next_id, draft.dirty = {}, 0, false
    else
      assert(services.insert, "Insertion is unavailable; copy instead")
      if services.insert_requires_confirmation ~= false
        and vim.fn.confirm("Insert into the ORIGINAL pane? Ensure its agent is at an editable prompt, not a dialog.\n"
          .. "No Return will be sent. Background process changes can still race this check.", "&Cancel\n&Insert", 1) ~= 2 then return end
      services.insert(payload)
    end
    session:close(true)
  end
  local function comment(initial, save, canceled)
    assert(not editor, "Finish or cancel the current comment")
    editor = scratch(vim.split(initial or "", "\n", { plain = true }), true)
    local buf = editor
    -- Unlike nofile, acwrite protects modified comments from a native :close.
    vim.bo[buf].buftype = "acwrite"
    vim.bo[buf].bufhidden = ""
    vim.bo[buf].modified = false
    vim.o.hidden = false
    local width = math.max(1, math.min(72, vim.o.columns - 4))
    local height = math.max(1, math.min(8, vim.o.lines - 6))
    local modal = vim.api.nvim_open_win(buf, true, { relative = "editor", style = "minimal", border = "rounded",
      width = width, height = height, row = 1, col = math.max(0, math.floor((vim.o.columns - width) / 2)),
      title = " Comment • Ctrl+s save • Esc then q cancel " })
    local function finish()
      editor = nil
      vim.api.nvim_win_close(modal, true)
      if vim.api.nvim_buf_is_valid(buf) then vim.api.nvim_buf_delete(buf, { force = true }) end
      vim.api.nvim_set_current_win(win)
    end
    vim.api.nvim_create_autocmd("WinClosed", { group = group, pattern = tostring(modal), once = true, callback = function()
      if editor == buf then
        editor = nil
        vim.schedule(function()
          if vim.api.nvim_buf_is_valid(buf) then vim.api.nvim_buf_delete(buf, { force = true }) end
        end)
      end
    end })
    local function contents() return table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") end
    mapping(buf, { "i", "n" }, "<C-s>", guarded(function()
      local value = contents()
      save(value) -- Invalid/blank content leaves this editor open.
      vim.cmd.stopinsert()
      finish()
      refresh()
    end))
    mapping(buf, "n", "q", function()
      if contents() == (initial or "") or discard("Discard this comment edit?") then
        finish()
        if canceled then canceled() end
      end
    end)
    vim.cmd.startinsert()
  end
  local function comment_selection()
    local mode = vim.fn.mode()
    assert(mode == "v" or mode == "V", "Use v or V to select text first")
    local from, to = vim.fn.getpos("v"), vim.fn.getpos(".")
    local selected = vim.fn.getregion(from, to, { type = mode, exclusive = false })
    local quote = table.concat(selected, "\n")
    if from[2] > to[2] or (from[2] == to[2] and from[3] > to[3]) then from, to = to, from end
    local start_row, end_row = from[2], to[2]
    -- One-based rows, zero-based UTF-8 byte columns, end-exclusive; scoped to this snapshot.
    local start_byte = mode == "V" and 0 or (from[3] - 1)
    local end_byte = #selected[#selected] + (start_row == end_row and start_byte or 0)
    local range_end_row, range_end_byte = end_row, end_byte
    -- A linewise quote includes its hard newline when one exists in the snapshot.
    if mode == "V" and end_row < #lines then
      quote = quote .. "\n"
      range_end_row, range_end_byte = end_row + 1, 0
    end
    local range = { start_row, start_byte, range_end_row, range_end_byte, mode = mode }
    vim.cmd.normal({ args = { vim.api.nvim_replace_termcodes("<Esc>", true, false, true) }, bang = true })
    comment("", function(value) draft:add(quote, value, range) end,
      function() vim.cmd.normal({ args = { "gv" }, bang = true }) end)
  end
  local function comment_current_line()
    local row = vim.api.nvim_win_get_cursor(win)[1]
    local quote = lines[row]
    local range_end_row, range_end_byte = row, #quote
    if row < #lines then
      quote = quote .. "\n"
      range_end_row, range_end_byte = row + 1, 0
    end
    comment("", function(value)
      draft:add(quote, value, { row, 0, range_end_row, range_end_byte, mode = "V" })
    end)
  end
  mapping(source, "x", "<CR>", guarded(comment_selection))
  mapping(source, "n", "<CR>", guarded(comment_current_line))
  mapping(source, "n", "m", function()
    if #draft.notes == 0 then notify("No annotations yet"); return end
    vim.ui.select(draft.notes, { prompt = "Annotations", format_item = function(note)
      return "[" .. note.id .. "] L" .. note.range[1] .. ":" .. (note.range[2] + 1) .. " " .. note.comment:gsub("\n", " ")
    end }, function(note)
      if not note then return end
      vim.ui.select({ "Edit", "Remove" }, { prompt = "Annotation " .. note.id }, guarded(function(choice)
        if choice == "Edit" then comment(note.comment, function(value) draft:edit(note.id, value) end)
        elseif choice == "Remove" then draft:remove(note.id); refresh() end
      end))
    end)
  end)
  local function preview_payload()
    assert(#draft.notes > 0, "Add an annotation first")
    preview = scratch(vim.split(draft:format(), "\n", { plain = true }))
    local buf = preview
    vim.api.nvim_win_set_buf(win, buf)
    local function back()
      vim.api.nvim_win_set_buf(win, source)
      vim.api.nvim_buf_delete(buf, { force = true })
      preview = nil
    end
    mapping(buf, "n", "q", back)
    mapping(buf, "n", "<Esc>", back)
    mapping(buf, "n", "y", guarded(function() deliver("copy") end))
    mapping(buf, "n", "s", guarded(function() deliver("insert") end))
    mapping(buf, "n", "S", guarded(function() deliver("send") end))
  end
  mapping(source, "n", "p", guarded(preview_payload))
  mapping(source, "n", "y", guarded(function() deliver("copy") end))
  mapping(source, "n", "s", guarded(function() deliver("insert") end))
  mapping(source, "n", "S", guarded(function() deliver("send") end))
  mapping(source, "n", "q", function() session:close() end)
  vim.api.nvim_create_autocmd("QuitPre", { group = group, callback = function()
    if draft.dirty or editor then
      if not discard("Discard unfinished annotations?") then error("Annotations kept open", 0) end
      if editor and vim.api.nvim_buf_is_valid(editor) then vim.bo[editor].modified = false end
    end
  end })
  refresh()
  return session
end

local function parse_timestamp(value)
  if type(value) ~= "string" then return nil end
  local year, month, day, hour, minute, second, suffix = value:match(
    "^(%d%d%d%d)%-(%d%d)%-(%d%d)[Tt ](%d%d):(%d%d):(%d%d)(.*)$")
  if not year then return nil end
  year, month, day = tonumber(year), tonumber(month), tonumber(day)
  hour, minute, second = tonumber(hour), tonumber(minute), tonumber(second)
  local zone = suffix
  if zone:sub(1, 1) == "." then zone = zone:match("^%.[0-9]+(.*)$") or "" end
  local offset = 0
  if zone ~= "Z" and zone ~= "z" then
    local sign, offset_hour, offset_minute = zone:match("^([+-])(%d%d):?(%d%d)$")
    if not sign then return nil end
    offset_hour, offset_minute = tonumber(offset_hour), tonumber(offset_minute)
    if offset_hour > 14 or offset_minute > 59 or (offset_hour == 14 and offset_minute ~= 0) then return nil end
    offset = (offset_hour * 60 + offset_minute) * (sign == "+" and 1 or -1)
  end
  local month_days = { 31, (year % 4 == 0 and (year % 100 ~= 0 or year % 400 == 0)) and 29 or 28,
    31, 30, 31, 30, 31, 31, 30, 31, 30, 31 }
  if year < 1 or month < 1 or month > 12 or day < 1 or day > month_days[month]
    or hour > 23 or minute > 59 or second > 59 then return nil end
  local adjusted_year = year - (month <= 2 and 1 or 0)
  local era = math.floor(adjusted_year / 400)
  local year_of_era = adjusted_year - era * 400
  local month_index = month + (month > 2 and -3 or 9)
  local day_of_year = math.floor((153 * month_index + 2) / 5) + day - 1
  local day_of_era = year_of_era * 365 + math.floor(year_of_era / 4) - math.floor(year_of_era / 100) + day_of_year
  return (era * 146097 + day_of_era - 719468) * 86400 + hour * 3600 + minute * 60 + second - offset * 60
end

local function relative_time(timestamp)
  local instant = parse_timestamp(timestamp)
  if not instant then return "?" end
  local delta = instant - os.time()
  local future = delta > 0
  local seconds = math.abs(delta)
  if seconds < 60 then return future and "+<1m" or "now" end
  local amount, unit
  if seconds < 3600 then amount, unit = math.floor(seconds / 60), "m"
  elseif seconds < 86400 then amount, unit = math.floor(seconds / 3600), "h"
  elseif seconds < 30 * 86400 then amount, unit = math.floor(seconds / 86400), "d"
  elseif seconds < 365 * 86400 then amount, unit = math.floor(seconds / (30 * 86400)), "mo"
  else amount, unit = math.floor(seconds / (365 * 86400)), "y" end
  local label = tostring(math.max(1, amount)) .. unit
  return future and ("+" .. label) or label
end

function M.pick_replies(replies, target, services, agent_title)
  agent_title = agent_title or "Pi"
  assert(type(agent_title) == "string" and agent_title:match("%S") and #agent_title <= 80,
    "Invalid assistant title")
  agent_title = agent_title:gsub("[%c]", " "):gsub("%s+", " "):gsub("^%s+", ""):gsub("%s+$", "")
  local heading = agent_title == "Pi" and "PI REPLIES" or agent_title .. " REPLIES"
  assert(type(replies) == "table" and #replies > 0,
    "No visible assistant replies in the active " .. agent_title .. " session")
  local lines = { "j/k move · Enter opens the selected reply · / search · q close", "" }
  local by_row = {}
  for index = #replies, 1, -1 do
    local reply = replies[index]
    assert(type(reply) == "table" and type(reply.text) == "string" and #reply.text > 0
      and #reply.text <= 4 * 1024 * 1024, "Invalid " .. agent_title .. " reply")
    assert(not reply.text:find("[%z\1-\8\11-\31\127]"),
      agent_title .. " reply contains unsupported control characters")
    local excerpt = reply.text:match("([^\n]+)") or "(blank reply)"
    excerpt = excerpt:gsub("[%c]", " "):gsub("%s+", " ")
    excerpt = vim.fn.strcharpart(excerpt, 0, 100)
    -- ASCII time labels fit six cells; previews always start at the same column.
    lines[#lines + 1] = string.format("%6s  %s", relative_time(reply.timestamp), excerpt)
    by_row[#lines] = reply
  end
  local buf = scratch(lines)
  local win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(win, buf)
  vim.wo[win].wrap = false
  vim.wo[win].number = false
  vim.wo[win].cursorline = true
  vim.wo[win].winbar = statusline_text(heading) .. " %<· newest first · Enter opens reply"
  vim.wo[win].statusline = " Rex Annotate · " .. statusline_text(agent_title) .. " active branch · %l/%L "
  vim.api.nvim_win_set_cursor(win, { 3, 0 })
  local picker = { picker = buf, replies = replies }
  local function open_reply(row)
    local reply = by_row[row]
    assert(reply, "Select an assistant reply first")
    vim.api.nvim_buf_delete(buf, { force = true })
    local source_title = agent_title == "Pi" and "PI REPLY" or agent_title .. " REPLY"
    picker.editor = M.open(reply.text, target, services, source_title)
    return picker.editor
  end
  mapping(buf, "n", "<CR>", guarded(function()
    return open_reply(vim.api.nvim_win_get_cursor(win)[1])
  end))
  mapping(buf, "n", "q", function()
    if services.quit then services.quit() else vim.cmd("qa!") end
  end)
  picker.select = open_reply
  return picker
end

local function api(method, args)
  local result = vim.system({ "rex", "--timeout", "5s", "api", "call", method, "-" }, {
    stdin = vim.json.encode(args), text = true, timeout = 6000,
  }):wait()
  assert(result.code == 0, "Rex request failed or timed out; draft kept. " .. (result.stderr or ""))
  return vim.json.decode(result.stdout)
end

function M.start(target)
  -- Covers q, :quit/:qa, and the startup-error screen, but only after any
  -- discard confirmation has allowed exit. Never steal deliberately moved focus.
  vim.api.nvim_create_autocmd("VimLeavePre", { once = true, callback = function()
    local ok, err = pcall(core.restore_focus, api, target, vim.env.REX_BLOCK)
    if not ok then notify("Could not restore source focus: " .. tostring(err)) end
  end })
  local ok, err = pcall(function()
    local original = core.identity(api("com.superlogical.terminal.process", {
      session_id = target.session_id, block_id = target.block_id, args = vim.empty_dict(),
    }))
    local pi_response, native_response
    local snapshot
    if original and original.agent == "Pi" then
      local ok, result = pcall(core.pi_request, target, original.pid, { op = "replies" })
      if not ok and tostring(result):find("Unsupported Pi annotation request", 1, true) then
        error("Pi PID " .. original.pid .. " needs the updated rex-annotation bridge. Install this checkout in Pi; "
          .. "reload that process only when it is safe to clear session-only auth.")
      end
      assert(ok, result)
      pi_response = result
      assert(type(pi_response.replies) == "table", "Pi bridge returned no reply list")
    elseif original then
      native_response = core.agent_request(target, original, { op = "replies" })
      assert(type(native_response.replies) == "table", "Agent adapter returned no reply list")
    else
      snapshot = core.capture(api, target)
    end
    local validate_session = native_response and function()
      core.agent_request(target, original, { op = "validate", sessionId = native_response.sessionId })
    end or nil
    local services = {
      -- Pi uses its exact-session editor API; raw terminal paste still needs a readiness check.
      insert_requires_confirmation = pi_response == nil,
      copy = function(payload)
        -- The launcher accepts local macOS clients only. Never use an unrelated host's clipboard.
        local result = vim.system({ "/usr/bin/pbcopy" }, { stdin = payload, timeout = 3000 }):wait()
        assert(result.code == 0, "Clipboard failed; draft kept")
      end,
      insert = function(payload)
        local pi_insert = pi_response and function(value)
          return core.pi_request(target, original.pid, { op = "insert", sessionId = pi_response.sessionId, text = value })
        end or nil
        core.insert(api, target, original, payload, pi_insert, validate_session)
      end,
      send = function(payload)
        local pi_send = pi_response and function(value)
          local ok, result = pcall(core.pi_request, target, original.pid,
            { op = "send", sessionId = pi_response.sessionId, text = value })
          if not ok and tostring(result):find("Unsupported Pi annotation request", 1, true) then
            error("Pi Send needs the updated rex-annotation bridge; annotations remain open. Reload Pi only when it is safe to clear session-only auth.")
          end
          assert(ok, result)
          return result
        end or nil
        core.send(api, target, original, payload, pi_send, validate_session)
      end,
      quit = function() vim.cmd("qa!") end,
    }
    local response = pi_response or native_response
    if response then M.pick_replies(response.replies, target, services, original.agent)
    else M.open(snapshot, target, services) end
  end)
  if not ok then
    local buf = scratch({ "Rex Annotate could not open:", tostring(err), "", "Press q to close. No input was sent." })
    vim.api.nvim_win_set_buf(0, buf)
    mapping(buf, "n", "q", function() vim.cmd("qa!") end)
  end
end

return M
