-- Rex annotation entry point. Load this module from its installed repository.
local pending = {}
local source_path = debug.getinfo(1, "S").source:gsub("^@", "")
local directory = assert(source_path:match("^(.*[/\\])"), "Missing plugin directory")

local function call(method, args)
  local result, err = rex.call(method, args)
  if not result then error(err or (method .. " failed"), 0) end
  return result
end

local function local_target(ctx)
  if not ctx.session_id or not ctx.block_id or not ctx.client_id then
    error("Run Annotate from a local Rex terminal pane", 0)
  end
  local source = call("session.describe_block", { session_id = ctx.session_id, block_id = ctx.block_id }).block
  local server = call("server.status", {})
  local client = call("client.inspect", { client_id = ctx.client_id }).client
  if source.creator_name ~= "com.superlogical.terminal" or not source.window_id then
    error("Annotate needs a placed terminal pane", 0)
  end
  if source.host_id ~= server.host_id or (client.principal or {}).transport ~= "unix"
    or (client.info or {}).platform ~= "macos" then
    error("Annotation v1 supports local macOS Rex clients only", 0)
  end
  return {
    session_id = ctx.session_id, block_id = ctx.block_id,
    window_id = source.window_id, client_id = ctx.client_id,
  }, source
end

local function executable(name)
  local found = rex.exec({ "/usr/bin/which", name }, { timeout = 3 })
  local candidates = { "/opt/homebrew/bin/" .. name, "/usr/local/bin/" .. name, "/usr/bin/" .. name }
  local resolved = found and found.ok and (found.stdout or ""):match("^(/[^\r\n]+)")
  if resolved then table.insert(candidates, 1, resolved) end
  for _, candidate in ipairs(candidates) do
    local result = rex.exec({ candidate, "--version" }, { timeout = 3 })
    if result and result.ok then return candidate end
  end
  error(name .. " is unavailable; install it on PATH or with Homebrew", 0)
end

local function open_annotation(ctx)
  local target, source = local_target(ctx)
  local key = ctx.session_id .. "/" .. ctx.block_id
  if pending[key] then error("An annotation view is already opening", 0) end
  pending[key] = true
  local ok, result = pcall(function()
    local label = "Annotation: " .. ctx.block_id
    local blocks = call("session.list_blocks", { session_id = ctx.session_id }).blocks or {}
    for _, block in ipairs(blocks) do
      if block.label == label then error("This pane already has an annotation view; close it first", 0) end
    end

    local core_path = directory .. "annotate_core.lua"
    local core_file = io.open(core_path, "r")
    if not core_file then error("Missing plugin helper " .. core_path .. "; reinstall rex-annotation", 0) end
    core_file:close()
    local core = dofile(core_path)
    local bounds = core.overlay_bounds(call("session.view", { session_id = ctx.session_id }), target)
    local target_json = rex.json.encode(target)
    local program = executable("nvim")
    local view = directory .. "annotate_view.lua"
    local file = io.open(view, "r")
    if not file then error("Missing plugin helper " .. view .. "; reinstall rex-annotation", 0) end
    file:close()
    local command = { program, "--noplugin", "-u", "NONE", "-i", "NONE", "-n",
      "--cmd", "set nomodeline noswapfile noundofile nobackup nowritebackup",
      "-c", string.format("lua dofile(%q).start(vim.json.decode(%q))", view, target_json) }

    local layer = call("session.new_layer", { session_id = ctx.session_id, window_id = source.window_id,
      bounds = bounds, focus = true,
      layout = { block = { flavor = "com.superlogical.terminal.shell", label = label,
        options = { shell = "none", login = false, command = command,
          exit = { on_completion = true, quick_exit_threshold_ms = 0 } } },
      },
    })
    local released, release_error = rex.call("session.disown_block", {
      session_id = ctx.session_id, block_ids = layer.block_ids,
    })
    if not released then
      local _, cleanup_error = rex.call("session.close_layer", { session_id = ctx.session_id, layer_id = layer.layer_id })
      error(tostring(release_error) .. (cleanup_error and ("; cleanup failed: " .. cleanup_error) or ""), 0)
    end
    return layer
  end)
  pending[key] = nil
  if not ok then error(result, 0) end
  return result
end

rex.action{
  name = "annotate_open", title = "Annotate Agent Reply or Terminal Output", category = "Annotations", args = {},
  description = "Pick an agent reply or capture terminal output; annotate, copy, insert, or send",
  run = function(ctx) return open_annotation(ctx) end,
}
rex.bind("ctrl+s>o", "annotate_open")
