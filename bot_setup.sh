#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "Done. Run ./bot_run.sh to start the Slack bot."
