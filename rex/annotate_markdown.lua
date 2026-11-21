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
  local function block(row, group)
    vim.api.nvim_buf_set_extmark(buf, ns, row, 0, { line_hl_group = group, priority = 75 })
  end
  vim.api.nvim_set_hl(0, "RexMarkdownHeading", { bold = true })
  vim.api.nvim_set_hl(0, "RexMarkdownMarker", { link = "Special" })
  vim.api.nvim_set_hl(0, "RexMarkdownQuote", { italic = true })
  vim.api.nvim_set_hl(0, "RexMarkdownCode", { link = "NormalFloat" })
  local fence
  for i, text in ipairs(lines) do
    local row = i - 1
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
    end
  end
end

return M
