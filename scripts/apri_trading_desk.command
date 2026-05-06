#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$ROOT/scripts/install_launch_agents.py" >/dev/null

if pgrep -f "$HOME/Library/Application Support/trading-control-plane/TradingDeskCompanion" >/dev/null; then
  exit 0
fi

exec /bin/zsh "$ROOT/scripts/run_swift_companion.sh"
