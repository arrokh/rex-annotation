-- Best-effort local watermark. Store only hashes; never store reply text or notes.
local M = {}
local uv = vim.uv

local function state_path(agent, conversation, state_home)
  local home = state_home or vim.env.XDG_STATE_HOME
  if not home or home == "" then home = vim.fn.expand("~/.local/state") end
  local directory = home .. "/rex-annotation/last-opened"
  vim.fn.mkdir(directory, "p", 448) -- 0700
  local stat = uv.fs_lstat(directory)
  assert(stat and stat.type == "directory" and stat.uid == uv.getuid() and stat.mode % 512 == 448)
  return directory .. "/" .. vim.fn.sha256(vim.json.encode({ agent, conversation }))
end

local function read(path)
  local stat = uv.fs_lstat(path)
  if not stat or stat.type ~= "file" or stat.uid ~= uv.getuid() or stat.size ~= 64 then return nil end
  local fd = uv.fs_open(path, "r", 0)
  if not fd then return nil end
  local value = uv.fs_read(fd, 64, 0)
  uv.fs_close(fd)
  return value and #value == 64 and value:match("^%x+$") or nil
end

local function write(path, value)
  local fd, temporary = uv.fs_mkstemp(path .. ".XXXXXX")
  if not fd then return end
  local bytes = uv.fs_write(fd, value, 0)
  local closed = uv.fs_close(fd)
  if bytes == #value and closed and uv.fs_rename(temporary, path) then return end
  uv.fs_unlink(temporary)
end

function M.reply_key(reply)
  if type(reply.id) ~= "string" or reply.id == "" then return nil end
  -- Older Pi bridges can return positional fallback IDs. Include the payload
  -- fingerprint there so a different branch's reply at that position won't match.
  if reply.id:match("^reply%-%d+$") then
    return vim.fn.sha256(vim.json.encode({ reply.id, reply.timestamp or "", reply.text }))
  end
  return vim.fn.sha256(reply.id)
end

function M.open(agent, conversation, latest, state_home)
  if type(conversation) ~= "string" or conversation == "" or not latest then return nil end
  local ok, path = pcall(state_path, agent, conversation, state_home)
  if not ok then return nil end
  local previous = read(path)
  if previous ~= latest then write(path, latest) end
  return previous
end

return M
