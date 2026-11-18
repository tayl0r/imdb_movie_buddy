#!/usr/bin/env bash
# Local checks and the deploy's test job (CLAUDE.md § Local checks): every root module must import.
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'EOF'
import importlib, os, pathlib, sys
from unittest import mock

sys.path.insert(0, os.getcwd())   # explicit, so PYTHONSAFEPATH can't drop the repo root

# slack_bolt isn't installed here, so stub only the names slack_bot uses at import; a misspelled one still fails.
slack_bolt = sys.modules["slack_bolt"] = mock.MagicMock(spec=["App"])
slack_bolt.App.return_value = mock.MagicMock(spec=["event", "action", "error"])
sys.modules["slack_bolt.adapter.socket_mode"] = mock.MagicMock(spec=["SocketModeHandler"])

for path in sorted(pathlib.Path(".").glob("[!.]*.py")):   # [!.]: not editor lock files like .#slack_bot.py
    try:
        importlib.import_module(path.stem)
    except SystemExit as e:   # chained, so the traceback names the file that exited, which may be one it imports
        raise RuntimeError(f"importing {path.name} exited ({e.code!r}): keep each script's work under if __name__ == '__main__':") from e
EOF
