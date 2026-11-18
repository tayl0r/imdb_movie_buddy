#!/usr/bin/env bash
# Local checks, and the deploy's test job (CLAUDE.md § Local checks). The repo has no test suite, so this is a
# basic check: every root module compiles and imports.
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'EOF'
import importlib, os, pathlib, sys
from unittest import mock

sys.path.insert(0, os.getcwd())   # explicit, so PYTHONSAFEPATH can't drop the repo root

# slack_bot needs slack_bolt, which isn't installed here, so stand in for it: what this catches is a broken
# import between the repo's own modules. Each stub holds only the names slack_bot imports, so a misspelled one
# still fails.
sys.modules["slack_bolt"] = mock.MagicMock(spec=["App"])
sys.modules["slack_bolt.adapter.socket_mode"] = mock.MagicMock(spec=["SocketModeHandler"])

for path in sorted(pathlib.Path(".").glob("*.py")):
    importlib.import_module(path.stem)
EOF
