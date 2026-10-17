#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
if [ "$(id -un)" != codex ]; then
  echo 'Run as the existing unprivileged codex user.' >&2
  exit 1
fi
python3 -m venv .venv-support
.venv-support/bin/python -m pip install -r telegram_support/requirements.txt
/home/codex/.local/bin/codex login status
printf '%s\n' 'Dependencies installed. Next, in this interactive terminal:' \
  '.venv-support/bin/python -m telegram_support.setup'
