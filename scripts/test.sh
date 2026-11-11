#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONDONTWRITEBYTECODE=1
node --check integrations/pi/bridge.js
node --check integrations/pi/extensions/index.js
node --test integrations/pi/test/*.test.mjs
nvim --headless --noplugin -u NONE -i NONE -n -l scripts/test-rex-annotate.lua
nvim --headless --noplugin -u NONE -i NONE -n -l scripts/test-agent-boundary.lua
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m unittest discover -s integrations/tests -p 'test_*.py'
