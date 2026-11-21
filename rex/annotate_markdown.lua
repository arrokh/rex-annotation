-- Visual formatting only. Keep source text, byte offsets and Vim motions intact.
local M = {}
local ns = vim.api.nvim_create_namespace("rex-annotate-markdown")

function M.apply(buf, lines)
  local function mark(row, start_col, end_col, group)
    if start_col < end_col then
      vim.api.nvim_buf_set_extmark(buf, ns, row, start_col, {
        end_col = end_col, hl_group = group, priority = 80,
      })
    end
  end
  local function conceal(row, first, last)
    vim.api.nvim_buf_set_extmark(buf, ns, row, first, {
      end_col = last, conceal = "", priority = 81, hl_group = "RexMarkdownMarker",
    })
  end
  local function inline(row, text, hide)
    if #text > 8192 then return end -- Keep very long generated lines cheap to open.
    -- Recognize simple inline spans, not nested or reference-style links.
    local patterns = {
      { "`([^`]+)`", "RexMarkdownInlineCode", 1 },
      { "%*%*([^*]+)%*%*", "RexMarkdownHeading", 2 },
      { "%[([^%[%]]+)%]%([^%s()]+%)", "RexMarkdownLink", 1 },
    }
    -- Process each style independently so a link inside bold keeps its label.
    local code_spans = {}
    for format_index, format in ipairs(patterns) do
      local from, code_index = 1, 1
      while from <= #text do
        local first, last, content = text:find(format[1], from)
        if not first then break end
        local in_code = false
        if format_index ~= 1 then
          while code_spans[code_index] and code_spans[code_index][2] < first do code_index = code_index + 1 end
          local code = code_spans[code_index]
          in_code = code and ((first >= code[1] and first <= code[2]) or (last >= code[1] and last <= code[2]))
        end
        if not in_code and (first == 1 or text:sub(first - 1, first - 1) ~= "\\") then
          if format_index == 1 then code_spans[#code_spans + 1] = { first, last } end
          local start = first - 1 + format[3]
          mark(row, start, start + #content, format[2])
          if hide then
            conceal(row, first - 1, start)
            conceal(row, start + #content, last)
          end
        end
        from = last + 1
      end
    end
  end
  local function cells(text)
    -- Ambiguous separators (escaped pipes or pipes in code) stay unaligned.
    if text:find("\\|", 1, true) or text:find("`[^`]*|[^`]*`") then return nil end
    local first = text:match("^ ? ? ?()|")
    if not first or not text:match("|[ \t]*$") then return nil end
    local result = {}
    for pos in text:gmatch("()|") do
      if #result == 12 then return nil end
      result[#result + 1] = pos
    end
    return #result >= 3 and result or nil
  end
  local function table_block(start)
    local header, separator = cells(lines[start]), lines[start + 1] and cells(lines[start + 1])
    if not header or not separator or #header ~= #separator then return nil end
    for col = 1, #separator - 1 do
      if not vim.trim(lines[start + 1]:sub(separator[col] + 1, separator[col + 1] - 1)):match("^:?-+:?$") then return nil end
    end
    local positions, widths = { [start] = header, [start + 1] = separator }, {}
    local finish = start + 1
    for index = start + 2, #lines do
      local positions_on_line = cells(lines[index])
      if not positions_on_line or #positions_on_line ~= #header then break end
      positions[index] = positions_on_line
      finish = index
    end
    local align = true
    for index = start, finish do
      local pipes = positions[index]
      for col = 1, #pipes - 1 do
        local width = vim.fn.strdisplaywidth(lines[index]:sub(pipes[col] + 1, pipes[col + 1] - 1))
        if width > 48 then align = false end
        widths[col] = math.max(widths[col] or 0, width)
      end
    end
    for index = start, finish do
      local pipes = positions[index]
      if index == start then mark(index - 1, 0, #lines[index], "RexMarkdownHeading") end
      for col, pos in ipairs(pipes) do
        mark(index - 1, pos - 1, pos, "RexMarkdownMarker")
        if align and col > 1 then
          local width = vim.fn.strdisplaywidth(lines[index]:sub(pipes[col - 1] + 1, pos - 1))
          local padding = widths[col - 1] - width
          if padding > 0 then
            vim.api.nvim_buf_set_extmark(buf, ns, index - 1, pos - 1, {
              virt_text = { { string.rep(index == start + 1 and "-" or " ", padding) } }, virt_text_pos = "inline",
            })
          end
        end
      end
    end
    return finish
  end
  local function block(row, group)
    vim.api.nvim_buf_set_extmark(buf, ns, row, 0, { line_hl_group = group, priority = 75 })
  end
  vim.api.nvim_set_hl(0, "RexMarkdownHeading", { bold = true })
  vim.api.nvim_set_hl(0, "RexMarkdownMarker", { link = "Special" })
  vim.api.nvim_set_hl(0, "RexMarkdownQuote", { italic = true })
  vim.api.nvim_set_hl(0, "RexMarkdownCode", { link = "NormalFloat" })
  vim.api.nvim_set_hl(0, "RexMarkdownInlineCode", { link = "String" })
  vim.api.nvim_set_hl(0, "RexMarkdownLink", { underline = true })
  local fence, table_end
  for i, text in ipairs(lines) do
    local row = i - 1
    if not fence and (not table_end or i > table_end) and text:find("|", 1, true) then table_end = table_block(i) end
    if table_end and i <= table_end then
      inline(row, text, false)
    else
      local indent, run, rest = text:match("^( *)(`+)(.*)$")
      if not run then indent, run, rest = text:match("^( *)(~+)(.*)$") end
      local marker = run and #indent <= 3 and #run >= 3 and run:sub(1, 1)
      if fence then
        block(row, "RexMarkdownCode")
        if marker == fence.char and #run >= fence.length and not rest:find("%S") then
          mark(row, #indent, #text, "RexMarkdownMarker")
          fence = nil
        end
      elseif marker and (marker ~= "`" or not rest:find("`", 1, true)) then
        fence = { char = marker, length = #run }
        block(row, "RexMarkdownCode")
        mark(row, #indent, #text, "RexMarkdownMarker")
      else
        local padding, heading, content = text:match("^( *)(#+)[ \t]+()")
        if not heading then padding, heading = text:match("^( *)(#+)$") end
        if heading and #padding <= 3 and #heading <= 6 then
          mark(row, #padding, #padding + #heading, "RexMarkdownMarker")
          if content then mark(row, content - 1, #text, "RexMarkdownHeading") end
        else
          local spaces, quote = text:match("^( *)(>)")
          if quote and #spaces <= 3 then
            mark(row, #spaces, #spaces + 1, "RexMarkdownMarker")
            mark(row, #spaces + 1, #text, "RexMarkdownQuote")
          else
            local prefix, bullet = text:match("^([ \t]*)([-+*])[ \t]+")
            if not bullet then prefix, bullet = text:match("^([ \t]*)(%d+[.)])[ \t]+") end
            if bullet then mark(row, #prefix, #prefix + #bullet, "RexMarkdownMarker") end
          end
        end
        inline(row, text, true)
      end
    end
  end
end

return M
