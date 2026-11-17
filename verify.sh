#!/usr/bin/env bash
# Local checks, and the deploy's test job (CLAUDE.md § Local checks). The repo has no test suite, so this is a
# basic check: every file compiles, and every module imports.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m compileall -q -l .

python3 - <<'EOF'
import importlib, os, pathlib, sys
from unittest import mock

# slack_bot needs slack_bolt (not installed here) and exits at import without IPTORRENTS_COOKIE, so stand in
# for both: what this catches is a broken import between the repo's own modules.
sys.modules["slack_bolt"] = sys.modules["slack_bolt.adapter.socket_mode"] = mock.MagicMock()
os.environ.setdefault("IPTORRENTS_COOKIE", "verify")

for path in sorted(pathlib.Path(".").glob("*.py")):
    importlib.import_module(path.stem)
EOF
