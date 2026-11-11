-- Synthetic delivery boundary regression; never connects to Rex or an agent.
local core = dofile("rex/annotate_core.lua")
local process = { foreground = { pid = 42, path = "/bin/codex" } }
local original = core.identity(process)
local target = { session_id = "owned-session", block_id = "owned-block" }
local events = {}
local function call(method, args)
  if method == "com.superlogical.terminal.process" then return process end
  if method == "com.superlogical.terminal.modes" then return { modes = { { number = 2004, set = true } } } end
  assert(method == "block.event")
  events[#events + 1] = args.event
  return {}
end
local validations = 0
core.insert(call, target, original, "payload", nil, function() validations = validations + 1 end)
assert(validations == 1 and #events == 1 and events[1].type == "paste")
events = {}
local ok = pcall(core.insert, call, target, original, "payload", nil, function() error("stale conversation") end)
assert(not ok and #events == 0)
validations = 0
local sent, err = pcall(core.send, call, target, original, "payload", nil, function()
  validations = validations + 1
  if validations == 2 then error("new conversation") end
end)
assert(not sent and tostring(err):find("Inspect the draft", 1, true))
assert(#events == 1 and events[1].type == "paste")
events = {}
core.send(call, target, original, "payload", nil, function() end)
assert(#events == 2 and events[1].type == "paste" and events[2].type == "key" and events[2].payload.key == "enter")
print("PASS delivery revalidates the exact conversation before paste and again before Send")
local system = vim.system
local observed
vim.system = function(command, options)
  observed = command
  assert(options.timeout == 6000)
  return { wait = function() return { code = 0, stdout = '{"sessionId":"conversation","replies":[]}' } end }
end
local response = core.agent_request(target, original, { op = "validate", sessionId = "conversation" })
vim.system = system
assert(response.sessionId == "conversation")
assert(observed[1] == "python3" and observed[2]:find("integrations/session_replies.py", 1, true))
assert(observed[3] == "validate" and observed[5] == "codex")
assert(observed[#observed] == "conversation")
print("PASS native-session adapter uses explicit argv and the saved conversation identity")
