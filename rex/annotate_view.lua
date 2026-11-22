-- A private Neovim view: reuse Vim motions/visual/search; only annotation glue lives here.
local directory = debug.getinfo(1, "S").source:sub(2):match("^(.*[/\\])")
local core = dofile(directory .. "annotate_core.lua")
local seen = dofile(directory .. "annotate_seen.lua")
local M = {}

local annotation_palette = {
  Comment = { dark = { 0xe2eaf4, 0x374a61, 253, 24 }, light = { 0x27384e, 0xdce5ef, 24, 254 } },
  Yes = { dark = { 0xe2eee3, 0x354f42, 253, 22 }, light = { 0x294239, 0xd8e8dc, 22, 194 } },
  No = { dark = { 0xf3e5e8, 0x5a3e48, 253, 52 }, light = { 0x50313c, 0xefdde3, 52, 225 } },
}

local function annotation_highlight(comment)
  local value = vim.trim(comment):lower()
  return "RexAnnotation" .. (value == "yes" and "Yes" or value == "no" and "No" or "Comment")
end

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

function M.open(snapshot, target, services, source_title, on_back, reply_drafts, reply_index)
  vim.o.modeline = false
  vim.o.shada = ""
  vim.o.backup = false
  vim.o.writebackup = false
  vim.o.clipboard = ""
  vim.o.mouse = ""
  local function set_annotation_colors()
    for kind, variants in pairs(annotation_palette) do
      local colors = variants[vim.o.background]
      vim.api.nvim_set_hl(0, "RexAnnotation" .. kind, {
        fg = colors[1], bg = colors[2], ctermfg = colors[3], ctermbg = colors[4],
      })
    end
  end
  set_annotation_colors()
  local lines = vim.split(snapshot, "\n", { plain = true })
  local source = scratch(lines)
  if on_back then dofile(directory .. "annotate_markdown.lua").apply(source, lines) end
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
  if on_back then
    vim.wo[win].conceallevel = 2
    -- Reveal Markdown delimiters on the active line in Visual mode.
    vim.wo[win].concealcursor = "n"
  end
  local ns = vim.api.nvim_create_namespace("rex-annotate")
  local draft = reply_drafts and reply_drafts.for_reply(reply_index) or core.draft(target.block_id)
  local function dirty()
    if reply_drafts then return reply_drafts.dirty() end
    return draft.dirty
  end
  local session = { source = source, draft = draft, namespace = ns }
  local group = vim.api.nvim_create_augroup("rex-annotate-" .. source, { clear = true })
  vim.api.nvim_create_autocmd("OptionSet", { group = group, pattern = "background", callback = set_annotation_colors })
  local editor, editor_quote, preview
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
    local actions = { "v/V select", "Enter note", "Ctrl+Y/N Yes/No", "n/N notes", "\\n/\\N search", "Ctrl+E edit", "m manage", "p preview",
      "y copy", "Shift+Enter insert", "Ctrl+Enter send", "Ctrl+W wrap" }
    if on_back then actions[#actions + 1] = "Esc list" end
    actions[#actions + 1] = "q close"
    for _, action in ipairs(actions) do
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
  local delivery_error
  local function refresh_status()
    if not vim.api.nvim_win_is_valid(win) then return end
    local wrap_state = vim.wo[win].wrap and "wrap" or "nowrap"
    local notes = reply_drafts and (#draft.notes .. " here / " .. reply_drafts.count() .. " total")
      or (#draft.notes .. " notes")
    vim.wo[win].statusline = " Rex Annotate · " .. notes .. " · "
      .. (delivery_error and statusline_text(delivery_error)
        or statusline_text(target.block_id) .. " · " .. wrap_state) .. " %=%l:%c "
  end
  local function refresh()
    vim.api.nvim_buf_clear_namespace(source, ns, 0, -1)
    for _, note in ipairs(draft.notes) do
      local start_row, start_col = note.range[1] - 1, note.range[2]
      local end_row, end_col = note.range[3] - 1, note.range[4]
      local highlight = annotation_highlight(note.comment)
      vim.api.nvim_buf_set_extmark(source, ns, start_row, start_col, {
        end_row = end_row, end_col = end_col, hl_group = highlight, priority = 120,
      })
      local label_row, label_col = end_row, end_col
      if note.range.mode == "V" and end_col == 0 and end_row > start_row then
        label_row = end_row - 1
        label_col = #lines[label_row + 1]
      end
      vim.api.nvim_buf_set_extmark(source, ns, label_row, label_col, {
        virt_text = { { "  [" .. note.id .. "] " .. vim.fn.strcharpart(note.comment:gsub("\n", " "), 0, 70), highlight } },
        virt_text_pos = "eol",
      })
    end
    vim.wo[win].winbar = ""
    refresh_header()
    refresh_status()
  end
  local function discard(message)
    return vim.fn.confirm(message, "&Keep editing\n&Discard", 1) == 2
  end
  function session:payload()
    if reply_drafts then return reply_drafts.format() end
    return draft:format()
  end
  function session:close(force, back_to_list)
    if closed then return true end
    if back_to_list and not on_back then return false end
    if not force and (editor or (not back_to_list and dirty()))
        and not discard("Discard unfinished annotations?") then return false end
    if back_to_list and not on_back() then
      notify("Reply list is no longer available")
      return false
    end
    closed = true
    -- A confirmed close or successful delivery may reveal the picker before quit.
    if reply_drafts and not back_to_list then reply_drafts.mark_clean() end
    vim.api.nvim_del_augroup_by_id(group)
    if not back_to_list and vim.api.nvim_win_is_valid(win) and vim.api.nvim_buf_is_valid(source) then
      vim.api.nvim_win_set_buf(win, source)
    end
    if vim.api.nvim_win_is_valid(header_win) then vim.api.nvim_win_close(header_win, true) end
    for _, buf in ipairs({ editor or false, editor_quote or false }) do
      if buf then
        for _, float in ipairs(vim.fn.win_findbuf(buf)) do
          if vim.api.nvim_win_is_valid(float) and vim.api.nvim_win_get_config(float).relative ~= "" then
            vim.api.nvim_win_close(float, true)
          end
        end
      end
    end
    for _, buf in ipairs({ editor or false, editor_quote or false, preview or false, header, source }) do
      if buf and vim.api.nvim_buf_is_valid(buf) then vim.api.nvim_buf_delete(buf, { force = true }) end
    end
    if not back_to_list and services.quit then services.quit() end
    return true
  end
  local function deliver(kind)
    local payload = session:payload()
    assert(payload ~= "", "Add an annotation first")
    if kind == "copy" then
      assert(services.copy, "Clipboard is unavailable")
      services.copy(payload)
      if reply_drafts then reply_drafts.mark_clean() else draft.dirty = false end
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
  local function attempt_delivery(kind)
    delivery_error = nil
    refresh_status()
    local ok, err = pcall(deliver, kind)
    if not ok then
      local message = tostring(err):gsub("\n.*", ""):gsub("^.-%.lua:%d+: ", "")
      if message:find("Pi is busy; wait for its editable prompt", 1, true) then
        message = "Pi busy. Notes kept; retry when idle."
      end
      delivery_error = message:gsub("[%c]", " ")
      refresh_status()
    end
  end
  local function comment(quote, initial, save, canceled)
    assert(not editor, "Finish or cancel the current comment")
    editor = scratch(vim.split(initial or "", "\n", { plain = true }), true)
    local buf = editor
    -- Unlike nofile, acwrite protects modified comments from a native :close.
    vim.bo[buf].buftype = "acwrite"
    vim.bo[buf].bufhidden = ""
    vim.bo[buf].modified = false
    vim.o.hidden = false
    local excerpt = scratch(vim.split(quote, "\n", { plain = true }))
    editor_quote = excerpt
    vim.bo[excerpt].bufhidden = "wipe"
    local function layout()
      local width = math.max(1, math.min(72, vim.o.columns - 4))
      local col = math.max(0, math.floor((vim.o.columns - width - 2) / 2))
      local quote_height = math.max(1, math.min(4, math.floor((vim.o.lines - 7) / 3)))
      local height = math.max(1, math.min(8, vim.o.lines - quote_height - 7))
      local common = { relative = "editor", style = "minimal", border = "rounded", width = width, col = col }
      return vim.tbl_extend("force", common, { row = 0, height = quote_height, focusable = false,
        title = width >= 28 and " Quote (PgUp/PgDn scroll) " or " Quote " }),
        vim.tbl_extend("force", common, { row = quote_height + 2, height = height,
          title = width >= 52 and " Enter save / Shift+Enter newline / Esc then q " or " Enter save ",
          footer = " ^Y Yes / ^N No " })
    end
    local quote_config, modal_config = layout()
    local quote_win = vim.api.nvim_open_win(excerpt, false, quote_config)
    vim.wo[quote_win].wrap = true
    vim.wo[quote_win].linebreak = true
    vim.wo[quote_win].smoothscroll = true
    local modal = vim.api.nvim_open_win(buf, true, modal_config)
    local resize = vim.api.nvim_create_autocmd("VimResized", { group = group, callback = function()
      if vim.api.nvim_win_is_valid(modal) and vim.api.nvim_win_is_valid(quote_win) then
        local quote_layout, modal_layout = layout()
        vim.api.nvim_win_set_config(quote_win, quote_layout)
        vim.api.nvim_win_set_config(modal, modal_layout)
      end
    end })
    local function cleanup()
      if editor_quote == excerpt then editor_quote = nil end
      if vim.api.nvim_win_is_valid(quote_win) then vim.api.nvim_win_close(quote_win, true) end
      if vim.api.nvim_buf_is_valid(buf) then vim.api.nvim_buf_delete(buf, { force = true }) end
    end
    vim.api.nvim_create_autocmd("WinClosed", { group = group, pattern = tostring(modal), once = true, callback = function()
      vim.api.nvim_del_autocmd(resize)
      if editor == buf then
        editor = nil
        -- Native close is still processing this window; defer buffer deletion.
        vim.schedule(cleanup)
      end
    end })
    local function finish()
      editor = nil
      vim.api.nvim_win_close(modal, true)
      cleanup()
      vim.api.nvim_set_current_win(win)
    end
    local function contents() return table.concat(vim.api.nvim_buf_get_lines(buf, 0, -1, false), "\n") end
    local function submit(value)
      save(value) -- Invalid/blank content leaves this editor open.
      vim.cmd.stopinsert()
      finish()
      refresh()
    end
    mapping(buf, { "i", "n" }, "<CR>", guarded(function() submit(contents()) end))
    mapping(buf, "i", "<S-CR>", "<CR>")
    mapping(buf, { "i", "n" }, "<C-y>", guarded(function() submit("Yes") end))
    mapping(buf, { "i", "n" }, "<C-n>", guarded(function() submit("No") end))
    for _, key in ipairs({ "<PageUp>", "<PageDown>" }) do
      mapping(buf, { "i", "n" }, key, guarded(function()
        vim.api.nvim_win_call(quote_win, function()
          local scroll = key == "<PageUp>" and "<C-y>" or "<C-e>"
          vim.cmd.normal({ bang = true, args = { vim.api.nvim_win_get_height(quote_win) .. vim.keycode(scroll) } })
        end)
      end))
    end
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
    comment(quote, "", function(value) draft:add(quote, value, range) end,
      function() vim.cmd.normal({ args = { "gv" }, bang = true }) end)
  end
  local function comment_current_line(quick_note)
    local row = vim.api.nvim_win_get_cursor(win)[1]
    local quote = lines[row]
    local range_end_row, range_end_byte = row, #quote
    if row < #lines then
      quote = quote .. "\n"
      range_end_row, range_end_byte = row + 1, 0
    end
    local function save(value)
      draft:add(quote, value, { row, 0, range_end_row, range_end_byte, mode = "V" })
    end
    if quick_note then
      save(quick_note)
      refresh()
    else
      comment(quote, "", save)
    end
  end
  local jumped
  local function before(row, col, other_row, other_col)
    return row < other_row or (row == other_row and col < other_col)
  end
  local function at_jump(cursor)
    return jumped and jumped.row == cursor[1] and jumped.col == cursor[2]
  end
  vim.api.nvim_create_autocmd("CursorMoved", { group = group, buffer = source, callback = function()
    if not at_jump(vim.api.nvim_win_get_cursor(win)) then jumped = nil end
  end })
  local function jump(direction)
    if #draft.notes == 0 then notify("No annotations yet"); return end
    local ordered = vim.list_extend({}, draft.notes)
    table.sort(ordered, function(a, b)
      local ar, br = a.range, b.range
      if ar[1] == br[1] and ar[2] == br[2] then return a.id < b.id end
      return before(ar[1], ar[2], br[1], br[2])
    end)
    local cursor = vim.api.nvim_win_get_cursor(win)
    local index
    for i, note in ipairs(ordered) do
      if at_jump(cursor) and note.id == jumped.id then index = i; break end
    end
    if index then
      index = (index - 1 + direction) % #ordered + 1
    else
      for i, note in ipairs(ordered) do
        local row, col = note.range[1], note.range[2]
        if direction == 1 and before(cursor[1], cursor[2], row, col) then index = i; break end
        if direction == -1 and before(row, col, cursor[1], cursor[2]) then index = i end
      end
      index = index or (direction == 1 and 1 or #ordered)
    end
    local note = ordered[index]
    vim.api.nvim_win_set_cursor(win, { note.range[1], note.range[2] })
    cursor = vim.api.nvim_win_get_cursor(win)
    jumped = { id = note.id, row = cursor[1], col = cursor[2] }
  end
  local function edit_note(note)
    comment(note.quote, note.comment, function(value) draft:edit(note.id, value) end)
  end
  local function edit_at_cursor()
    local cursor = vim.api.nvim_win_get_cursor(win)
    local match
    for _, note in ipairs(draft.notes) do
      if at_jump(cursor) and note.id == jumped.id then edit_note(note); return end
      local r = note.range
      if not match and not before(cursor[1], cursor[2], r[1], r[2])
        and before(cursor[1], cursor[2], r[3], r[4]) then match = note end
    end
    if match then edit_note(match) else notify("No annotation here; jump with n or N") end
  end
  local next_note = guarded(function() jump(1) end)
  local prev_note = guarded(function() jump(-1) end)
  mapping(source, "n", "n", next_note)
  mapping(source, "n", "N", prev_note)
  -- Preserve native search, including direction, count, and wrapscan.
  vim.keymap.set("n", "\\n", "n", { buffer = source, silent = true })
  vim.keymap.set("n", "\\N", "N", { buffer = source, silent = true })
  mapping(source, "n", "<C-e>", guarded(edit_at_cursor))
  mapping(source, "x", "<CR>", guarded(comment_selection))
  mapping(source, "n", "<CR>", guarded(comment_current_line))
  mapping(source, "n", "<C-y>", guarded(function() comment_current_line("Yes") end))
  mapping(source, "n", "<C-n>", guarded(function() comment_current_line("No") end))
  mapping(source, "n", "m", function()
    if #draft.notes == 0 then notify("No annotations yet"); return end
    vim.ui.select(draft.notes, { prompt = "Annotations", format_item = function(note)
      return "[" .. note.id .. "] L" .. note.range[1] .. ":" .. (note.range[2] + 1) .. " " .. note.comment:gsub("\n", " ")
    end }, function(note)
      if not note then return end
      vim.ui.select({ "Edit", "Remove" }, { prompt = "Annotation " .. note.id }, guarded(function(choice)
        if choice == "Edit" then edit_note(note)
        elseif choice == "Remove" then draft:remove(note.id); refresh() end
      end))
    end)
  end)
  local function preview_payload()
    local payload = session:payload()
    assert(payload ~= "", "Add an annotation first")
    preview = scratch(vim.split(payload, "\n", { plain = true }))
    local buf = preview
    vim.api.nvim_win_set_buf(win, buf)
    local function back()
      vim.api.nvim_win_set_buf(win, source)
      vim.api.nvim_buf_delete(buf, { force = true })
      preview = nil
    end
    mapping(buf, "n", "q", back)
    mapping(buf, "n", "<Esc>", back)
    mapping(buf, "n", "y", function() attempt_delivery("copy") end)
    mapping(buf, "n", "<S-CR>", function() attempt_delivery("insert") end)
    mapping(buf, "n", "<C-CR>", function() attempt_delivery("send") end)
  end
  mapping(source, "n", "<C-w>", guarded(function()
    vim.wo[win].wrap = not vim.wo[win].wrap
    refresh_status()
  end))
  mapping(source, "n", "p", guarded(preview_payload))
  mapping(source, "n", "y", function() attempt_delivery("copy") end)
  mapping(source, "n", "<S-CR>", function() attempt_delivery("insert") end)
  mapping(source, "n", "<C-CR>", function() attempt_delivery("send") end)
  if on_back then
    mapping(source, "n", "<Esc>", guarded(function() session:close(false, true) end))
  end
  mapping(source, "n", "q", function() session:close() end)
  vim.api.nvim_create_autocmd("QuitPre", { group = group, callback = function()
    if dirty() or editor then
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

function M.pick_replies(replies, target, services, agent_title, conversation, state_home)
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
  -- Take one snapshot per pane. Returning from a reply reuses this buffer.
  if conversation then
    local previous = seen.open(agent_title, conversation, seen.reply_key(replies[#replies]), state_home)
    if previous then
      for row = 3, #lines do
        if seen.reply_key(by_row[row]) == previous then
          lines[row] = lines[row]:sub(1, 8) .. "[Last opened] " .. lines[row]:sub(9)
          break
        end
      end
    end
  end
  local buf = scratch(lines)
  local win = vim.api.nvim_get_current_win()
  vim.api.nvim_win_set_buf(win, buf)
  vim.wo[win].wrap = false
  vim.wo[win].number = false
  vim.wo[win].cursorline = true
  vim.wo[win].winbar = statusline_text(heading) .. " %<· newest first · Enter opens reply"
  local drafts = core.reply_drafts(target.block_id, #replies)
  local note_marks = vim.api.nvim_create_namespace("rex-annotate-picker-notes")
  local function note_count(count) return count .. (count == 1 and " note" or " notes") end
  local function picker_status()
    vim.wo[win].statusline = " Rex Annotate · " .. statusline_text(agent_title)
      .. " active branch · " .. note_count(drafts.count()) .. " · %l/%L "
  end
  local function refresh_note_mark(row)
    local index = row - 2
    local count = drafts.count(index)
    if count == 0 then
      vim.api.nvim_buf_del_extmark(buf, note_marks, index)
    else
      -- Put the count before the excerpt so it remains visible in narrow panes.
      vim.api.nvim_buf_set_extmark(buf, note_marks, row - 1, 8, {
        id = index, virt_text = { { "[" .. note_count(count) .. "] ", "Special" } },
        virt_text_pos = "inline",
      })
    end
  end
  picker_status()
  local function can_quit()
    return not drafts.dirty() or vim.fn.confirm("Discard unfinished annotations?", "&Keep editing\n&Discard", 1) == 2
  end
  vim.api.nvim_create_autocmd("QuitPre", { buffer = buf, callback = function()
    if not can_quit() then error("Annotations kept open", 0) end
  end })
  vim.api.nvim_win_set_cursor(win, { 3, 0 })
  local picker = { picker = buf, replies = replies }
  local function open_reply(row)
    local reply = by_row[row]
    assert(reply, "Select an assistant reply first")
    local selected_cursor = vim.api.nvim_win_get_cursor(win)
    local picker_options = {
      wrap = vim.wo[win].wrap,
      number = vim.wo[win].number,
      cursorline = vim.wo[win].cursorline,
      conceallevel = vim.wo[win].conceallevel,
      concealcursor = vim.wo[win].concealcursor,
      winbar = vim.wo[win].winbar,
    }
    local function on_back()
      if not vim.api.nvim_win_is_valid(win) or not vim.api.nvim_buf_is_valid(buf) then return false end
      vim.api.nvim_win_set_buf(win, buf)
      vim.wo[win].wrap = picker_options.wrap
      vim.wo[win].number = picker_options.number
      vim.wo[win].cursorline = picker_options.cursorline
      vim.wo[win].conceallevel = picker_options.conceallevel
      vim.wo[win].concealcursor = picker_options.concealcursor
      vim.wo[win].winbar = picker_options.winbar
      refresh_note_mark(row)
      picker_status()
      vim.api.nvim_win_set_cursor(win, selected_cursor)
      vim.api.nvim_set_current_win(win)
      return true
    end
    local source_title = agent_title == "Pi" and "PI REPLY" or agent_title .. " REPLY"
    picker.editor = M.open(reply.text, target, services, source_title, on_back, drafts, row - 2)
    return picker.editor
  end
  mapping(buf, "n", "<CR>", guarded(function()
    return open_reply(vim.api.nvim_win_get_cursor(win)[1])
  end))
  mapping(buf, "n", "q", function()
    if not can_quit() then return end
    drafts.mark_clean() -- Do not prompt again during the native quit event.
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
    if response then
      M.pick_replies(response.replies, target, services, original.agent, response.sessionId)
    else
      M.open(snapshot, target, services)
    end
  end)
  if not ok then
    local error_lines = { "Rex Annotate could not open:" }
    vim.list_extend(error_lines, vim.split(tostring(err), "\n", { plain = true }))
    vim.list_extend(error_lines, { "", "Press q to close. No input was sent." })
    local buf = scratch(error_lines)
    vim.api.nvim_win_set_buf(0, buf)
    mapping(buf, "n", "q", function() vim.cmd("qa!") end)
  end
end

return M
